# Banking Research Agent

A multi-tool research agent for banking analysts that autonomously searches Wikipedia, arXiv, and FRED to answer financial research questions with citations.


---

## Architecture Overview

### Orchestration: ReAct (Reasoning + Acting)

The agent uses the **ReAct** pattern — an interleaved loop of reasoning steps and tool calls:

```
Question
   │
   ▼
Classifier (LLM call)
   ├── out_of_scope → Refusal message
   └── in_scope
        │
        ▼
   ReAct Loop (up to 8 steps)
   ┌──────────────────────────────┐
   │  Thought  (LLM reasoning)    │
   │  Action   (tool + query)     │
   │  Observation (tool result)   │
   └──────────┬───────────────────┘
              │ repeat
              ▼
        Final Answer
        (retrieved facts + model reasoning, clearly separated)
              │
              ▼
        Trace saved to traces/{run_id}.json
```

**Why ReAct over alternatives:**

- **vs. plan-and-execute**: ReAct adapts mid-run. If a Wikipedia search for "Basel III" returns a high-level overview but not capital ratios specifically, the agent can immediately follow up on the gap. Plan-and-execute locks in the search plan upfront and can't course-correct.
- **vs. single-shot prompting**: Multi-step questions (e.g. comparing 2008 vs COVID monetary policy, or combining FRED data with academic context) require information from multiple tool calls to answer well. Single-shot doesn't retrieve anything.
- **vs. custom FSM**: ReAct is simpler to implement and inspect, and sufficient for this scope. A FSM would add value for highly structured workflows (e.g. always fetch FRED data first, then Wikipedia context) but introduces rigidity without a clear benefit here.

### Upfront Classifier

Before the ReAct loop begins, a lightweight LLM call classifies the question:

- **scope**: `in_scope` or `out_of_scope` — out-of-scope questions are refused immediately without any tool calls
- **domain**: `factual`, `academic`, `data`, `multi_source`, or `speculative` — passed to the ReAct loop as a hint to bias tool selection

### Answer Format

Every final answer explicitly separates what came from tools versus what the model inferred:

```
**[RETRIEVED — from tool results]**
<facts drawn directly from tool outputs, with inline [Source: url] citations>

**[REASONING — model analysis/inference]**
<synthesis, comparison, or inference the model added>
```

This distinction is enforced at the prompt level — the LLM is required to populate separate `retrieved` and `reasoning` fields in its JSON response.

### Observability

Every run produces a structured JSON trace in `traces/{run_id}.json` containing:
- Classifier result (scope, domain)
- Each step: thought, action (tool + query), full tool observation
- Final answer and citations
- Per-step and total duration

An index of all runs is appended to `traces/index.jsonl` for easy querying.

---

## Key Design Decisions

### LLM: Groq (llama-3.3-70b-versatile)

**Choice**: Groq's free tier running `llama-3.3-70b-versatile`.

**Why Groq over a local model:**
- No GPU required — reviewers can run the agent on any machine without installing Ollama or downloading multi-GB weights
- `llama-3.3-70b-versatile` has strong instruction-following and JSON output reliability, which matters for the ReAct loop's structured response format
- Groq's inference is fast enough that multi-step runs complete in seconds rather than minutes

**Model fallback**: If you hit rate limits with `llama-3.3-70b-versatile`, switch to `llama-3.1-8b-instant` in `core/llm.py` — it runs on a separate rate-limit pool on Groq's free tier. Reasoning quality is weaker but it's practical for batch eval runs. Automatic fallback between models is listed as a future improvement.

**Tradeoffs vs. a local model (e.g. Ollama + Llama 3.2-3B):**

| | Groq (free tier) | Local (Ollama) |
|---|---|---|
| Setup | API key only | Requires Ollama + model download (~2-8 GB) |
| Reproducibility | Requires internet + free account | Fully offline after setup |
| Reasoning quality | Strong (70B parameters) | Weaker at small sizes; 7B+ needed for reliable JSON |
| Rate limits | Yes (~30 RPM on free tier) | None |
| Cost | Free up to limits | Free, but compute-heavy on CPU |

**Tradeoffs vs. a paid API (e.g. GPT-4, Claude):**
Paid APIs offer higher rate limits and stronger reasoning, but violate the "no paid API keys" constraint. Groq free tier is the best available option that a reviewer can reproduce without spending money.

**Rate limiting**: The Groq client uses exponential backoff (up to 5 retries, base delay 2s) to handle 429s gracefully.

### Tool Interface

All tools implement a consistent `BaseTool` interface:

```python
class BaseTool(ABC):
    name: str         # identifier used by the LLM to invoke the tool
    description: str  # shown to the LLM in the system prompt

    def run(self, query: str) -> ToolResult: ...
```

```python
@dataclass
class ToolResult:
    tool_name: str
    query: str
    results: list[dict]   # raw structured data (stored in trace)
    summary: str          # compact text injected into LLM context
    source_urls: list[str]
    error: str | None
```

The separation between `results` (raw) and `summary` (LLM-ready) is intentional: raw data is preserved in the trace for citation accuracy, while the summary is a compact rendering that keeps the LLM context window manageable.

### Tool: Wikipedia

- **API**: MediaWiki REST API + Action API (no key required)
- **What it provides**: Article search, summaries, URLs
- **Best for**: Factual background, regulatory definitions, historical context (discount window, Basel III, Dodd-Frank, quantitative easing)
- **Implementation**: Searches for up to 3 article titles, fetches each summary via the REST `/page/summary/{title}` endpoint, returns them concatenated

### Tool: arXiv

- **API**: arXiv Atom feed API (no key required)
- **What it provides**: Paper titles, abstracts, authors, publication dates, arXiv IDs and URLs
- **Best for**: Recent academic research on ML in finance, systemic risk, credit modeling, stress testing
- **Implementation**: Queries `export.arxiv.org/api/query` sorted by relevance, parses Atom XML, returns up to 5 papers with formatted metadata

### Tool: FRED (Federal Reserve Economic Data)

- **API**: FRED REST API (free key, instant signup at [fredaccount.stlouisfed.org](https://fredaccount.stlouisfed.org))
- **What it provides**: US economic time series — unemployment, GDP, federal funds rate, inflation
- **Best for**: Data retrieval questions requiring current or historical figures
- **Graceful degradation**: If `FRED_API_KEY` is not set, the tool is registered but disabled — FRED questions fall back to Wikipedia rather than crashing
- **Implementation**: Searches FRED for the most relevant series by popularity, fetches the last 13 observations (~1 year for monthly series), returns values with dates and units

### Adding a New Tool

Adding a fourth tool is a three-step plug-in operation:
1. Create `tools/your_tool.py` implementing `BaseTool`
2. Register it in `core/tool_registry.py` → `build_default_registry()`
3. The tool description is automatically included in the agent's system prompt — no other changes needed

---

## Setup & Run Instructions

### Requirements

- Python 3.9 or higher
- A free [Groq API key](https://console.groq.com) (no credit card required)
- Optional: A free [FRED API key](https://fredaccount.stlouisfed.org/login/secure/) for economic data questions

### Install

```bash
# Clone the repo
git clone https://github.com/sydneywehn/research-agent.git
cd research-agent

# Install dependencies
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```
GROQ_API_KEY=gsk_...        # required
FRED_API_KEY=...            # optional — enables economic data questions
```

### Run a single question

```bash
python3 agent.py "What is the Federal Reserve's discount window and how does it work?"
```

Output is printed to stdout. A structured trace is saved to `traces/`.

### Run the evaluation harness

```bash
# Run all 18 benchmark questions
python3 evals/run_evals.py

# Run specific questions by ID
python3 evals/run_evals.py --ids q01 q07

# Filter by category
python3 evals/run_evals.py --category academic
```

Results are saved to `evals/results/eval_{timestamp}.json`.

---

## Agent Performance Summary

The agent was evaluated against an 18-question benchmark spanning factual lookup, academic search, data retrieval, multi-source synthesis, out-of-scope detection, and speculative questions.

**First full eval run: 14/18 (77%)**

| Category | Score |
|---|---|
| Academic | 3/3 |
| Data | 3/3 |
| Out-of-scope | 2/2 |
| Speculative | 1/1 |
| Multi-source | 3/4 |
| Factual | 2/5 |

**What worked well:** Academic paper retrieval, FRED data questions, and out-of-scope detection all performed perfectly. Multi-source synthesis questions (e.g. comparing 2008 vs COVID monetary policy) produced well-cited answers using multiple tools in a single run.

**Where it falls short:** Factual questions requiring specific sub-concepts (e.g. "primary credit rate" or "lender of last resort" within the discount window question) sometimes produced surface-level answers when the first Wikipedia result gave a high-level overview without drilling into specifics.

---

## Reference Question Outputs


### Q: What is the Federal Reserve's discount window and how does it work?
**[RETRIEVED — from tool results]**
The discount window is an instrument of monetary policy that allows eligible institutions to borrow money from the central bank, usually on a short-term basis, to meet temporary shortages of liquidity caused by internal or external disruptions [Source: https://en.wikipedia.org/wiki/Discount_window]. The total borrowings from the Federal Reserve as of 2026-02-01 were 4647.0 million dollars [Source: https://fred.stlouisfed.org/series/obs/BORROW]

**[REASONING — model analysis/inference]**
The discount window plays a crucial role in maintaining the stability of the financial system by providing a safety net for banks to meet their short-term liquidity needs. The recent borrowing data suggests that banks have been actively using the discount window to manage their liquidity, with borrowings fluctuating over the past year. This suggests that the discount window is an important tool for monetary policy and financial stability [REASONING].

### Q: What are the Basel III capital requirements for banks?
**[RETRIEVED — from tool results]**
Basel III is a framework that sets international standards and minimums for bank capital requirements, stress tests, liquidity regulations, and leverage [Source: https://en.wikipedia.org/wiki/Basel_III]. The Basel III accord was developed in response to the deficiencies in financial regulation revealed by the 2008 financial crisis [Source: https://en.wikipedia.org/wiki/Basel_III].

**[REASONING — model analysis/inference]**
Model reasoning suggests that the exact capital requirements for banks under Basel III are not explicitly stated in the retrieved information. However, it can be inferred that Basel III introduces new capital charges for banks, including a leverage ratio and risk-based capital requirements [REASONING].

### Q: What recent academic research exists on using machine learning for credit risk assessment?
**[RETRIEVED — from tool results]**
The arXiv search results include papers such as 'Changing Data Sources in the Age of Machine Learning for Official Statistics' [Source: https://arxiv.org/abs/2306.04338v1], 'Active learning for data streams: a survey' [Source: https://arxiv.org/abs/2302.08893v4], 'Physics-Inspired Interpretability Of Machine Learning Models' [Source: https://arxiv.org/abs/2304.02381v2], 'Privacy-preserving machine learning for healthcare: open challenges and future perspectives' [Source: https://arxiv.org/abs/2303.15563v1], and 'DOME: Recommendations for supervised machine learning validation in biology' [Source: https://arxiv.org/abs/2006.16189v4].

**[REASONING — model analysis/inference]**
While the search results do not provide direct information on using machine learning for credit risk assessment, they highlight the growing importance of machine learning in various fields and the need for reliable and accurate data-driven decision-making. The application of machine learning in credit risk assessment is a significant area of research, and it is likely that relevant papers may be found with more specific search queries or in other academic databases.

### Q: How did the Federal Reserve's monetary policy response to the 2008 financial crisis differ from its response to COVID-19?
**[RETRIEVED — from tool results]**
The Federal Reserve's response to the 2008 financial crisis involved invoking emergency authority to authorize new broad-based programs and financial assistance to stabilize financial markets, with loans outstanding peaking at over $1 trillion in late 2008 [Source: https://en.wikipedia.org/wiki/Federal_Reserve_response_to_the_subprime_crisis]. The Federal Reserve implemented quantitative easing (QE) programs, liquidity facilities, and forward guidance operations from 2007 to 2018 [Source: https://arxiv.org/abs/2305.12318v1]. During the COVID-19 pandemic, the Federal Reserve engaged in expansionary monetary policy, including measures to boost real activity and calm financial markets [Source: https://arxiv.org/abs/2007.15419v1].

**[REASONING — model analysis/inference]**
The differences in the Federal Reserve's monetary policy responses to the 2008 financial crisis and the COVID-19 pandemic can be attributed to the distinct economic conditions and challenges posed by each crisis. The 2008 financial crisis required a more comprehensive and unconventional monetary policy response, including quantitative easing and emergency lending facilities, to stabilize the financial system. In contrast, the COVID-19 pandemic required a more targeted and flexible monetary policy response, including measures to support small businesses and households affected by the pandemic. [REASONING] The Federal Reserve's communication strategies during the COVID-19 pandemic also differed from those during previous periods of economic stress, with a distinct focus on unconventional monetary policy and financial stability [Source: https://arxiv.org/abs/2508.04830v1].

### Q: What is the current US unemployment rate and how has it changed over the past year?
**[RETRIEVED — from tool results]**
The current US unemployment rate is 4.3% as of 2026-03-01 [Source: https://fred.stlouisfed.org/series/observations?series_id=UNRATE]. Recent observations include: 4.2% on 2025-03-01, 4.2% on 2025-04-01, 4.3% on 2025-05-01, 4.1% on 2025-06-01, 4.3% on 2025-07-01, 4.3% on 2025-08-01, 4.4% on 2025-09-01, 4.5% on 2025-11-01, 4.4% on 2025-12-01, 4.3% on 2026-01-01, 4.4% on 2026-02-01, and 4.3% on 2026-03-01 [Source: https://fred.stlouisfed.org/series/observations?series_id=UNRATE].

**[REASONING — model analysis/inference]**
Model reasoning suggests that the US unemployment rate has remained relatively stable over the past year, with some fluctuations. The rate decreased from 4.5% in November 2025 to 4.3% in January 2026 and remained at 4.3% as of March 2026.

### Q: Explain the relationship between yield curve inversions and recessions. Are there recent academic papers on this topic?
**[RETRIEVED — from tool results]**
Yield curve inversions have been used as a predictor of recessions [Source: https://arxiv.org/abs/2101.09394v2]. A study found that the predictive ability of the yield spread can be improved by using machine learning algorithms to identify the best maturity pair and coefficients [Source: https://arxiv.org/abs/2101.09394v2]. Another study used penalized logistic regression models to predict the Great Recession and the Covid-19 recession in real-time [Source: https://arxiv.org/abs/2310.08536v5]. The E-Rule, a novel composite recession indicator, combines the yield curve and the Sahm rule to provide a holistic and early-warning measure of economic downturns [Source: https://arxiv.org/abs/2503.09839v1].

**[REASONING — model analysis/inference]**
Model reasoning suggests that the yield curve inversion is a significant indicator of recessions, and recent academic papers support this claim. The use of machine learning algorithms and composite indicators can improve the accuracy of recession predictions. However, it is essential to consider multiple factors and indicators when predicting recessions.

### Q: What is the best restaurant in New York City?
This question is outside the scope of this financial research assistant.

Reason: The question is about restaurants, which is a non-financial topic.

I can help with banking regulations, monetary policy, economic data, academic finance research, and related topics.

### Q: What are the implications of quantum computing for banking encryption?
**[RETRIEVED — from tool results]**
Quantum computers can solve certain mathematical problems, such as integer factorization and discrete logarithm problems, which are the basis for many encryption algorithms [Source: https://en.wikipedia.org/wiki/Post-quantum_cryptography]. Post-quantum cryptography is the development of cryptographic algorithms that are secure against attacks by a quantum computer [Source: https://en.wikipedia.org/wiki/Post-quantum_cryptography]. Researchers are exploring new cryptographic algorithms, such as those based on lattice problems, hash functions, and code-based cryptography [Source: https://arxiv.org/abs/1109.3235v1, https://arxiv.org/abs/2402.00922v1].

**[REASONING — model analysis/inference]**
The development of post-quantum cryptography is crucial for the banking sector, as current encryption methods may be vulnerable to quantum computer attacks. The use of post-quantum cryptography can provide long-term security for banking transactions and data [Model Reasoning]. The impact of post-quantum cryptography on Central Bank Digital Currency (CBDC) is also being explored, with researchers examining the effects on CBDC design and security [Model Reasoning].

---

## Multi-Step Reasoning Examples

### Example 1: Multi-source synthesis

**Multi-step output (5 steps):**

**Question:** How did the Federal Reserve's monetary policy response to the 2008 financial crisis differ from its response to COVID-19?
Full trace available at: `traces/bc040a8f.json`

**Why multi-step helps:** This question requires information from multiple sources — Wikipedia for historical context, arXiv for academic analysis of QE programs, and FRED for economic data. A single-pass agent would only retrieve one source. Over 5 steps the agent searched Wikipedia, pivoted to arXiv for academic papers on QE, and cross-referenced COVID-19 monetary policy research before synthesizing.

**Answer:**
**[RETRIEVED — from tool results]**
The Federal Reserve's response to the 2008 financial crisis involved invoking emergency authority to authorize new broad-based programs and financial assistance to stabilize financial markets, with loans outstanding peaking at over $1 trillion in late 2008 [Source: Wikipedia]. The Federal Reserve implemented quantitative easing (QE) programs, liquidity facilities, and forward guidance operations from 2007 to 2018 [Source: arXiv]. During the COVID-19 pandemic, the Federal Reserve engaged in expansionary monetary policy, including measures to boost real activity and calm financial markets [Source: arXiv].

**[REASONING — model analysis/inference]**
The 2008 crisis required a more comprehensive unconventional response to stabilize the financial system. The COVID-19 response was more targeted, focused on supporting small businesses and households rather than systemic financial stabilization.


**Single-pass output (MAX_STEPS=1):**
The Federal Reserve's monetary policy response to the 2008 financial crisis and COVID-19 differed in terms of the specific policies implemented. During the 2008 crisis, the Federal Reserve implemented emergency authority to authorize new broad-based programs, with loans outstanding peaking at more than $1 trillion in late 2008. In contrast, during COVID-19, the Federal Reserve established programs like the Main Street Lending Program and Municipal Liquidity Facility.

*Sources: 3 Wikipedia articles only*

**Why multi-step is better:** The single-pass answer relies solely on Wikipedia and misses the academic analysis of QE programs and COVID monetary policy that arXiv provided in the multi-step run. The multi-step answer synthesizes across Wikipedia, arXiv, and FRED — producing a more complete, cited comparison.

---

### Example 2: Query self-correction

**Multi-step output (4 steps):**

**Question:** What recent academic research exists on using machine learning for credit risk assessment?
Full trace available at: `traces/48e9c6e1.json`


**Why multi-step helps:** The agent's first arXiv query returned off-topic results. Over 4 steps it rephrased the query three times, demonstrating self-correction based on intermediate results — a capability that single-pass prompting cannot replicate. The agent's reasoning section honestly acknowledged when retrieved results were not directly on-topic.

**Answer:**
**[RETRIEVED — from tool results]**
The arXiv search results include papers such as 'Changing Data Sources in the Age of Machine Learning for Official Statistics' [Source: https://arxiv.org/abs/2306.04338v1], 'Active learning for data streams: a survey' [Source: https://arxiv.org/abs/2302.08893v4], and 'Physics-Inspired Interpretability Of Machine Learning Models' [Source: https://arxiv.org/abs/2304.02381v2].

**[REASONING — model analysis/inference]**
While the search results do not provide direct information on using machine learning for credit risk assessment, they highlight the growing importance of machine learning in various fields. The agent identified this gap and rephrased its query three times before synthesizing from the best available results — demonstrating honest acknowledgment of retrieval limitations rather than hallucinating citations.

**Single-pass output (MAX_STEPS=1):**
Unable to synthesize a complete answer. (Sources: 4 arXiv papers returned but none directly on-topic)

**Why multi-step is better:** With only one step, the agent retrieved off-topic papers and couldn't synthesize an answer. Over 4 steps the multi-step agent rephrased its query three times, found the best available results, and produced a reasoned response — even acknowledging the retrieval gap honestly rather than failing silently.

---

## Limitations


- **Groq free tier rate limits**: Running the full 18-question eval suite sequentially triggers rate limiting (~30 RPM). In production this would be resolved with a paid API tier, request queuing, or a locally-hosted model.
- **Wikipedia retrieval depth**: The agent sometimes stops at a high-level article summary without following up on specific sub-concepts mentioned in the question. Better query decomposition upfront would improve factual recall.
- **arXiv query relevance**: Broad queries sometimes return tangentially related papers. More specific financial terminology in the query (e.g. "credit risk neural network 2024" vs "machine learning credit") improves results significantly.
- **No document store**: The agent only searches live APIs — it has no ability to search internal documents or PDFs, which limits its usefulness for a real banking startup's internal research.
- **Single-turn only**: The agent does not support follow-up questions or conversational context across runs.
---

## What I'd Do Differently With More Time

- **Better query planning**: Before entering the ReAct loop, decompose the question into explicit sub-questions and map each to the most appropriate tool. I implemented this but rolled it back after it increased LLM calls per question and triggered Groq free tier rate limits during eval runs. With a paid API tier or local model, this would be the highest-ROI improvement for factual question recall.
- **SQLite trace store**: Replace JSON trace files with a SQLite database for queryable run history — enabling analysis like "which questions used the most steps" or "which tool was called most often."
- **Local model fallback**: Add Ollama support as a fallback when Groq is rate-limited, with automatic switching. This would make the agent more resilient for batch eval runs.
- **Smarter Wikipedia retrieval**: Follow Wikipedia internal links when the first article summary is too high-level — similar to how a human researcher would click through to related articles.
- **Streaming output**: Print the agent's thoughts in real time rather than waiting for the full answer, which would make the tool much more usable interactively.
- **Internal document support**: Add a vector store tool (e.g. ChromaDB) so the agent can search internal PDFs and documents alongside public APIs.
- **Component-level evals**: The current eval harness measures end-to-end answer quality, but individual components (classifier accuracy, retrieval relevance, answer synthesis quality) should each have their own test suite. This would make it easier to isolate failures — e.g. is a bad answer caused by poor retrieval or poor synthesis?
- **Inline clickable citations**: Format the final answer with numbered footnotes or markdown hyperlinks so citations are embedded inline rather than listed at the bottom. This would make the output more readable and directly verify-able by the analyst.
- **Automatic model fallback**: Switch from `llama-3.3-70b-versatile` to `llama-3.1-8b-instant` automatically when rate limits are hit, rather than requiring a manual config change.
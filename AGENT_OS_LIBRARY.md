# Agent_OS

**A lightweight, production-grade Python framework for building AI agents with minimal boilerplate.**

Eliminate 80% of boilerplate code. Build production-ready agents in <50 lines instead of 100+.

---

## ✨ Features

### Core Capabilities
- 🛠️ **20+ Pre-built Tools** - Wikipedia, ArXiv, Web scraping, File processing, Email, GCP, Shell, and more
- 🤖 **Ready-to-use Agents** - Research, Data Analysis, Support, Code Review
- 🔄 **Multi-Agent Workflows** - Chain, conditional routing, parallel execution
- 💾 **Memory System** - Semantic (vector DB), episodic (action history), caching
- 📋 **YAML Configuration** - Define agents declaratively, no code needed

### Production Features (Tier 2 & 3)
- 🔒 **Reliability Layer**
  - Circuit Breaker Pattern - Auto-disable failing agents
  - Exponential Backoff Retry - Handle transient failures
  - Timeout Enforcement - Prevent runaway executions

- 💰 **Cost Management**
  - Budget Tracking - Daily/weekly/monthly limits
  - Token Usage Monitoring - Real-time cost tracking
  - Hard Limits - Auto-stop at budget threshold
  - Multi-model pricing database (OpenAI, Anthropic, Google)

- 🚦 **Rate Limiting**
  - Token Bucket Algorithm - Smooth rate limiting
  - Per-model limits - TPM and RPM enforcement
  - Auto-throttling - Exponential backoff

- 📊 **Observability**
  - Performance Metrics - Latency, throughput, error rates (P50/P95/P99)
  - Cost Attribution - Per-agent, per-tenant tracking
  - Execution Tracing - Full audit trails
  - Health Monitoring - Circuit breaker states, rate limits

- 🛡️ **Security**
  - CSV Injection Prevention - Automatic sanitization
  - SQL Injection Detection - Pattern-based blocking
  - PII Detection - Regex-based masking (coming soon)

---

## 🚀 Quick Start

### Installation

```bash
# Clone repository
git clone <repository-url>
cd AgentOS

# Install in development mode
pip install -e .

# Set API key
export OPENAI_API_KEY=your_key_here  # Linux/Mac
set OPENAI_API_KEY=your_key_here     # Windows CMD
```

### Create Your First Agent (5 lines)

```python
from agent_os import BaseAgent

agent = BaseAgent.from_yaml("configs/researcher.yaml")
result = agent.run("Find papers on RAG")
print(result)
```

### Create Custom Agent (Programmatic)

```python
from agent_os.agents.base import BaseAgent
from agent_os.tools.registry import ToolRegistry
from agent_os.tools.library.wikipedia import WikipediaSearchTool
from agent_os.tools.library.arxiv import ArxivSearchTool

# Setup tools
registry = ToolRegistry()
registry.register(WikipediaSearchTool())
registry.register(ArxivSearchTool())

# Create agent
agent = BaseAgent(
    name="ResearchBot",
    tools=["wikipedia_search", "arxiv_search"],
    model="gpt-4o-mini",
    temperature=0,
    tool_registry=registry,

    # Production features
    enable_cost_tracking=True,
    enable_circuit_breaker=True,
    enable_metrics=True
)

# Use it
result = agent.run("Research transformer neural networks")
```

---

## 📖 Documentation

### Guides
- **[Custom Tools & Agents Guide](CUSTOM_TOOLS_GUIDE.md)** - Complete tutorial on creating custom tools and agents
- **[Refactor Guide](REFACTOR_GUIDE.md)** - Architecture and design decisions
- **[Claude.md](claude.md)** - Implementation plan and roadmap

### Example Configs
- [Simple Agent](examples/configs/custom_agent_simple.yaml) - Minimal YAML config
- [Production Agent](examples/configs/custom_agent_production.yaml) - Full production config
- [Specialized Agent](examples/configs/custom_agent_specialized.yaml) - Domain-specific config

### Code Examples
- [Custom Tool Example](examples/custom_tool_example.py) - 4 ways to create tools
- [Simple Usage](examples/simple_usage.py) - Minimal examples
- [All Examples](examples/) - 19+ working examples

---

## 🛠️ Creating Custom Tools

### Method 1: Decorator (Fastest)

```python
from agent_os.tools.decorators import reliable_tool

@reliable_tool(
    name="word_counter",
    category="text",
    description="Count words in text"
)
def count_words(text: str) -> int:
    return len(text.split())
```

### Method 2: BaseTool Class (Production)

```python
from agent_os.tools.base import BaseTool, ToolMetadata

class WeatherTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="get_weather",
            description="Get weather for a city",
            category="utilities"
        )
        super().__init__(metadata)

    def _execute(self, city: str) -> dict:
        # Your implementation
        return {"temperature": 72, "condition": "sunny"}
```

**See [CUSTOM_TOOLS_GUIDE.md](CUSTOM_TOOLS_GUIDE.md) for complete documentation.**

---

## 📊 Pre-built Tools (20+)

### Research
- Wikipedia Search - Background information
- ArXiv Search - Academic papers
- Citation Generator - APA/MLA/Chicago formats

### Web
- Web Scraper - Extract data from websites
- HTTP Request - Make API calls
- URL Validator - Validate and parse URLs

### Data
- CSV Processor - Analyze CSV files (with injection prevention)
- JSON Parser - Parse and transform JSON
- File Reader - Read text files
- PDF Text Extractor - Extract text from PDFs

### Text Processing
- Text Summarizer - Condense text
- Grammar Checker - Check grammar
- Language Detection - Detect language
- Sentiment Analysis - Analyze sentiment

### Utilities
- Email Sender - Send emails
- Shell Executor - Run shell commands
- GCP Integration - Google Cloud Platform tools

**Full list:** [agent_os/tools/library/](agent_os/tools/library/)

---

## 🔄 Multi-Agent Workflows

```python
from agent_os.workflows.builder import WorkflowBuilder

# Create agents
researcher = BaseAgent(name="Researcher", tools=["wikipedia_search"])
summarizer = BaseAgent(name="Summarizer", tools=["text_summarize"])
reviewer = BaseAgent(name="Reviewer", tools=["grammar_check"])

# Build workflow: Research → Summarize → Review
workflow = WorkflowBuilder({
    "research": researcher,
    "summarize": summarizer,
    "review": reviewer
}).chain(["research", "summarize", "review"]).build()

# Execute
result = workflow.invoke({"query": "Research AI agents"})
```

---

## 💰 Cost Tracking & Budgets

```python
from agent_os.utils.cost_tracker import Budget

agent = BaseAgent(
    name="ProductionAgent",
    tools=["wikipedia_search"],
    model="gpt-4o-mini",

    enable_cost_tracking=True,
    budget=Budget(
        limit=10.0,           # $10 budget
        window="daily",       # Reset daily
        hard_limit=True,      # Stop at limit
        warning_threshold=0.8 # Warn at 80%
    )
)

# Check costs
info = agent.get_info()
print(f"Cost: ${info['cost_tracker']['total_cost']:.4f}")
print(f"Budget: ${info['cost_tracker']['budget_remaining']:.2f} remaining")
```

---

## 📈 Performance Metrics

```python
agent = BaseAgent(
    name="MetricsAgent",
    tools=["wikipedia_search"],
    enable_metrics=True
)

# Use agent
result = agent.run("Search Wikipedia")

# Get metrics
metrics = agent.get_metrics()
print(f"Latency P95: {metrics.p95_latency_ms:.2f}ms")
print(f"Success Rate: {metrics.successful_requests / metrics.total_requests:.1%}")
print(f"Error Rate: {metrics.error_rate:.1%}")
```

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_tier3_metrics.py -v

# Run with coverage
pytest tests/ --cov=agent_os --cov-report=html
```

**Current test status:** ✅ 119 tests passing

---

## 📁 Project Structure

```
agent_os/
├── agents/          # Agent implementations
│   ├── base.py      # BaseAgent class
│   └── factory.py   # Agent factory
├── tools/           # Tool system
│   ├── base.py      # BaseTool class
│   ├── decorators.py # Tool decorators
│   ├── registry.py  # Tool registry
│   └── library/     # 20+ pre-built tools
├── workflows/       # Multi-agent workflows
├── config/          # YAML configuration
├── utils/           # Utility modules
│   ├── circuit_breaker.py  # Circuit breaker pattern
│   ├── cost_tracker.py     # Cost tracking
│   ├── rate_limiter.py     # Rate limiting
│   ├── retry.py            # Retry logic
│   ├── timeout.py          # Timeout enforcement
│   ├── metrics.py          # Performance metrics
│   └── errors.py           # Error handling
└── memory/          # Memory system

examples/            # 19+ working examples
tests/               # Test suite (119 tests)
```

---

## 🎯 Success Criteria

### Before (Without AgentOS)
```python
# 50+ lines of boilerplate
from langchain_openai import ChatOpenAI
from langchain.agents import create_react_agent
# ... more imports ...

async def run_agent(query: str):
    server_config = {...}
    client = MultiServerMCPClient({'research': server_config})
    tools = await client.get_tools()
    model = ChatOpenAI(model="gpt-4o-mini")
    agent = create_react_agent(model, tools)
    result = await agent.ainvoke({"messages": [...]})
    # ... more code ...
```

### After (With AgentOS)
```python
# 5 lines total
from agent_os import BaseAgent

agent = BaseAgent.from_yaml("configs/researcher.yaml")
result = agent.run("Find papers on RAG")
print(result)
```

**Code Reduction: 90%**

---

## 🏗️ Architecture Highlights

- **Provider Agnostic** - OpenAI, Anthropic, Google, Azure OpenAI
- **Framework Flexible** - LangChain, LangGraph, MCP support
- **Production Ready** - Circuit breakers, retries, budgets, metrics
- **Developer Friendly** - YAML configs, decorators, minimal boilerplate
- **Enterprise Scale** - Multi-tenancy ready, cost attribution, audit logs

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

---

## 📄 License

[Your License Here]

---

## 🙏 Acknowledgments

Built with:
- [LangChain](https://github.com/langchain-ai/langchain) - Agent framework
- [LangGraph](https://github.com/langchain-ai/langgraph) - Workflow orchestration
- [Pydantic](https://github.com/pydantic/pydantic) - Data validation
- [OpenAI](https://openai.com/) - LLM provider

---

## 📞 Support

- **Documentation:** See [CUSTOM_TOOLS_GUIDE.md](CUSTOM_TOOLS_GUIDE.md)
- **Examples:** Check [examples/](examples/) directory
- **Issues:** Open GitHub issue
- **Questions:** See [discussions](../../discussions)

---

**Happy Building! 🚀**

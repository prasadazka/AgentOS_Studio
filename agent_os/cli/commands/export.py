"""Export agent configs to Python code"""

from pathlib import Path
from typing import Optional
from rich.console import Console

from agent_os.cli.core.config_generator import ConfigGenerator
from agent_os.cli.ui.formatters import format_success, format_error
from agent_os.tools.registry import ToolRegistry

console = Console()


def export_agent_to_python(
    agent_name: str,
    output_path: Optional[str] = None,
    tool_registry: Optional[ToolRegistry] = None,
    silent: bool = False
) -> Optional[str]:
    """
    Export agent YAML config to standalone Python code.

    Args:
        agent_name: Name of the agent to export
        silent: If True, suppress console output
        output_path: Output file path (optional, defaults to <agent_name>.py)
        tool_registry: Tool registry instance

    Returns:
        Path to generated Python file, or None if failed
    """
    generator = ConfigGenerator()

    try:
        config = generator.load_and_validate_config("agents", agent_name)
    except FileNotFoundError:
        if not silent:
            console.print(format_error(
                f"Agent '{agent_name}' not found",
                suggestions=[
                    "Run 'agent_os list agents' to see available agents",
                ]
            ))
        return None
    except Exception as e:
        if not silent:
            console.print(format_error(f"Failed to load agent config: {e}"))
        return None

    # Generate Python code
    tools_list = config.get("tools", [])
    tools_str = ", ".join(f'"{tool}"' for tool in tools_list) if tools_list else ""

    python_code = f'''"""
Agent: {config["name"]}
Generated from YAML config by AgentOS

Setup:
    1. Create a .env file in the same directory with:
       OPENAI_API_KEY=sk-proj-your-key-here

    2. Or set environment variable:
       export OPENAI_API_KEY=sk-proj-your-key-here  # Linux/Mac
       set OPENAI_API_KEY=sk-proj-your-key-here     # Windows

Usage:
    python {agent_name}.py "your question here"
"""

from agent_os import Agent
import sys
import os

# Try to load .env file if it exists (optional but recommended)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, will use system environment variables
    pass


def main():
    """Run {config["name"]} agent"""

    # Check if API key is available
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Error: OPENAI_API_KEY not found!")
        print("\\nPlease set your API key using one of these methods:")
        print("1. Create a .env file: OPENAI_API_KEY=sk-proj-...")
        print("2. Set environment variable: export OPENAI_API_KEY=sk-proj-...")
        print("3. Run: python -c 'import os; os.environ[\\"OPENAI_API_KEY\\"] = \\"sk-...\\"; exec(open(\\"{agent_name}.py\\").read())'")
        sys.exit(1)

    # Create agent
    agent = Agent.create(
        name="{config["name"]}",
        tools=[{tools_str}],
        model="{config.get("model", "gpt-4o-mini")}",
        temperature={config.get("temperature", 0.0)},
        prompt="""{config.get("system_prompt", "")}"""
    )

    # Get query from command line or prompt
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Query: ")

    # Run agent
    print(f"\\n[{config["name"]}] Processing...\\n")
    response = agent.run(query)
    print(f"\\n[Response]\\n{{response}}\\n")


if __name__ == "__main__":
    main()
'''

    # Create professional folder structure
    if output_path is None:
        # Create folder named after agent in current directory
        agent_folder = Path.cwd() / agent_name
        agent_folder.mkdir(exist_ok=True)
        output_file = agent_folder / f"{agent_name}.py"
    else:
        output_file = Path(output_path)
        agent_folder = output_file.parent

    # Write to file
    try:
        output_file.write_text(python_code, encoding="utf-8")

        # Create .env.example file
        env_example_file = agent_folder / ".env.example"
        env_example_content = """# AgentOS Configuration
# Copy this file to .env and fill in your actual API key

# OpenAI API Key (required)
# Get yours at: https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-proj-your-key-here

# Optional: Other API keys for tools
# ANTHROPIC_API_KEY=your-key-here
# GOOGLE_API_KEY=your-key-here
"""
        env_example_file.write_text(env_example_content, encoding="utf-8")

        # Create .gitignore file
        gitignore_file = agent_folder / ".gitignore"
        gitignore_content = """# Environment variables (contains secrets)
.env

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
"""
        gitignore_file.write_text(gitignore_content, encoding="utf-8")

        # Create requirements.txt
        requirements_file = agent_folder / "requirements.txt"
        requirements_content = """# AgentOS core
agent-os>=0.1.0

# Environment variables
python-dotenv>=1.0.0

# LLM providers
langchain>=0.3.0
langchain-openai>=0.2.0
"""
        # Add tool-specific requirements
        if tools_list:
            requirements_content += "\n# Tools\n"
            if "wikipedia_search" in tools_list:
                requirements_content += "wikipedia-api>=0.7.0\n"
            if "arxiv_search" in tools_list:
                requirements_content += "arxiv>=2.1.0\n"
            if any("pdf" in tool.lower() for tool in tools_list):
                requirements_content += "PyPDF2>=3.0.0\n"

            # DataFrame tools
            dataframe_tools = [
                "dataframe_read_excel", "dataframe_write_excel",
                "dataframe_read_parquet", "dataframe_write_parquet",
                "dataframe_describe", "dataframe_filter_rows",
                "dataframe_drop_duplicates", "dataframe_handle_missing",
                "dataframe_sort", "dataframe_add_column",
                "dataframe_group_aggregate", "dataframe_merge",
                "dataframe_convert_types", "dataframe_clean_outliers",
                "dataframe_correlation", "dataframe_validate_schema",
                "dataframe_quality_report", "dataframe_visualize",
                "dataframe_fetch_api", "dataframe_pivot",
                "dataframe_analyze_folder"
            ]
            if any(tool in tools_list for tool in dataframe_tools):
                requirements_content += "\n# Data Analysis\n"
                requirements_content += "pandas>=2.2.0\n"
                if any(tool in tools_list for tool in ["dataframe_read_excel", "dataframe_write_excel"]):
                    requirements_content += "openpyxl>=3.1.0\n"
                if any(tool in tools_list for tool in ["dataframe_read_parquet", "dataframe_write_parquet"]):
                    requirements_content += "pyarrow>=15.0.0\n"
                # psutil needed for memory monitoring in all DataFrame tools
                requirements_content += "psutil>=5.9.0\n"
                # Visualization dependencies
                if "dataframe_visualize" in tools_list:
                    requirements_content += "matplotlib>=3.8.0\nseaborn>=0.13.0\n"
                # API fetch dependencies
                if "dataframe_fetch_api" in tools_list:
                    requirements_content += "httpx>=0.27.0\n"

        requirements_file.write_text(requirements_content, encoding="utf-8")

        # Create README.md
        readme_file = agent_folder / "README.md"
        readme_content = f"""# {config["name"]}

Generated from YAML config by AgentOS

## Description

{config.get("system_prompt", "AI agent")[:200]}...

## Configuration

- **Model**: {config.get("model", "gpt-4o-mini")}
- **Temperature**: {config.get("temperature", 0.0)}
- **Tools**: {", ".join(tools_list) if tools_list else "None (general purpose)"}

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Key

Copy `.env.example` to `.env` and add your OpenAI API key:

```bash
cp .env.example .env
```

Edit `.env`:
```
OPENAI_API_KEY=sk-proj-your-actual-key-here
```

### 3. Run the Agent

```bash
python {agent_name}.py "your question here"
```

Or run interactively:

```bash
python {agent_name}.py
```

## Usage Examples

```bash
# Example 1: Command line argument
python {agent_name}.py "your question"

# Example 2: Interactive mode
python {agent_name}.py
# Then type your question when prompted
```

## Project Structure

```
{agent_name}/
├── {agent_name}.py      # Main agent script
├── .env.example         # Environment template
├── .env                 # Your API keys (gitignored)
├── .gitignore          # Git ignore rules
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Security Notes

- Never commit `.env` file to version control
- The `.gitignore` file is configured to prevent accidental commits
- Store your API keys securely

## Generated by AgentOS

Created with [AgentOS](https://github.com/yourusername/agent-os) - Production-grade AI agent framework
"""
        readme_file.write_text(readme_content, encoding="utf-8")

        if not silent:
            details = {
                "Agent": agent_name,
                "Folder": str(agent_folder.absolute()),
                "Files": f"{agent_name}.py, README.md, requirements.txt, .env.example, .gitignore",
                "Setup": f"cd {agent_name} && pip install -r requirements.txt",
                "Run": f"python {agent_name}/{agent_name}.py 'your question'",
            }

            console.print(format_success(
                f"Exported agent to professional project structure",
                details=details
            ))
        return str(output_file)
    except Exception as e:
        if not silent:
            console.print(format_error(f"Failed to write Python file: {e}"))
        return None


def export_agent_as_class(
    agent_name: str,
    output_path: Optional[str] = None,
    tool_registry: Optional[ToolRegistry] = None
) -> Optional[str]:
    """
    Export agent as a reusable Python class.

    Args:
        agent_name: Name of the agent to export
        output_path: Output file path (optional)
        tool_registry: Tool registry instance

    Returns:
        Path to generated Python file, or None if failed
    """
    generator = ConfigGenerator()

    try:
        config = generator.load_and_validate_config("agents", agent_name)
    except Exception as e:
        console.print(format_error(f"Failed to load agent: {e}"))
        return None

    tools_list = config.get("tools", [])
    tools_str = ", ".join(f'"{tool}"' for tool in tools_list) if tools_list else ""
    class_name = config["name"].replace(" ", "").replace("-", "").replace("_", "")

    python_code = f'''"""
{config["name"]} - Reusable Agent Class
Generated by AgentOS

Setup:
    Create a .env file with: OPENAI_API_KEY=sk-proj-your-key-here
    Or set environment variable before importing this class.

Usage:
    from {agent_name}_class import {class_name}

    agent = {class_name}()
    response = agent.ask("your question")
    print(response)
"""

from agent_os import Agent
from typing import Optional
import os

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class {class_name}:
    """
    {config["name"]} agent

    Tools: {", ".join(tools_list) if tools_list else "None (general purpose)"}
    Model: {config.get("model", "gpt-4o-mini")}

    Raises:
        RuntimeError: If OPENAI_API_KEY is not set
    """

    def __init__(self):
        """Initialize {config["name"]}"""
        # Validate API key is available
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY not found. "
                "Please set it in .env file or environment variables."
            )

        self.agent = Agent.create(
            name="{config["name"]}",
            tools=[{tools_str}],
            model="{config.get("model", "gpt-4o-mini")}",
            temperature={config.get("temperature", 0.0)},
            prompt="""{config.get("system_prompt", "")}"""
        )

    def ask(self, query: str) -> str:
        """
        Ask the agent a question.

        Args:
            query: Your question

        Returns:
            Agent's response
        """
        return self.agent.run(query)

    async def ask_async(self, query: str) -> str:
        """Async version of ask()"""
        return await self.agent.arun(query)


# Example usage
if __name__ == "__main__":
    import sys

    try:
        agent = {class_name}()

        if len(sys.argv) > 1:
            query = " ".join(sys.argv[1:])
            response = agent.ask(query)
            print(f"\\n{{response}}\\n")
        else:
            print(f"{class_name} initialized. Use agent.ask('your question') to interact.")
    except RuntimeError as e:
        print(f"⚠️  Error: {{e}}")
        print("\\nSetup instructions:")
        print("1. Create .env file: OPENAI_API_KEY=sk-proj-...")
        print("2. Or: export OPENAI_API_KEY=sk-proj-...")
'''

    # Create professional folder structure
    if output_path is None:
        # Create folder named after agent in current directory
        agent_folder = Path.cwd() / agent_name
        agent_folder.mkdir(exist_ok=True)
        output_file = agent_folder / f"{agent_name}_class.py"
    else:
        output_file = Path(output_path)
        agent_folder = output_file.parent

    try:
        output_file.write_text(python_code, encoding="utf-8")

        # Create .env.example file
        env_example_file = agent_folder / ".env.example"
        if not env_example_file.exists():
            env_example_content = """# AgentOS Configuration
# Copy this file to .env and fill in your actual API key

# OpenAI API Key (required)
# Get yours at: https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-proj-your-key-here

# Optional: Other API keys for tools
# ANTHROPIC_API_KEY=your-key-here
# GOOGLE_API_KEY=your-key-here
"""
            env_example_file.write_text(env_example_content, encoding="utf-8")

        # Create .gitignore if not exists
        gitignore_file = agent_folder / ".gitignore"
        if not gitignore_file.exists():
            gitignore_content = """# Environment variables (contains secrets)
.env

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
"""
            gitignore_file.write_text(gitignore_content, encoding="utf-8")

        # Create requirements.txt if not exists
        requirements_file = agent_folder / "requirements.txt"
        if not requirements_file.exists():
            requirements_content = """# AgentOS core
agent-os>=0.1.0

# Environment variables
python-dotenv>=1.0.0

# LLM providers
langchain>=0.3.0
langchain-openai>=0.2.0
"""
            requirements_file.write_text(requirements_content, encoding="utf-8")

        # Create README for class export
        readme_file = agent_folder / "README.md"
        readme_content = f"""# {config["name"]} - Reusable Class

Generated by AgentOS as a reusable Python class

## Description

{config.get("system_prompt", "AI agent")[:200]}...

## Configuration

- **Model**: {config.get("model", "gpt-4o-mini")}
- **Temperature**: {config.get("temperature", 0.0)}
- **Tools**: {", ".join(tools_list) if tools_list else "None (general purpose)"}

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Key

Copy `.env.example` to `.env` and add your OpenAI API key:

```bash
cp .env.example .env
```

Edit `.env`:
```
OPENAI_API_KEY=sk-proj-your-actual-key-here
```

## Usage

### As a Module

```python
from {agent_name}_class import {class_name}

# Initialize agent
agent = {class_name}()

# Ask questions
response = agent.ask("your question here")
print(response)

# Async usage
import asyncio
response = asyncio.run(agent.ask_async("your question"))
```

### Standalone Script

```bash
python {agent_name}_class.py "your question here"
```

## Project Structure

```
{agent_name}/
├── {agent_name}_class.py   # Agent class module
├── .env.example            # Environment template
├── .env                    # Your API keys (gitignored)
├── .gitignore             # Git ignore rules
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## API Reference

### Class: `{class_name}`

#### Methods

- `ask(query: str) -> str`: Synchronous query execution
- `ask_async(query: str) -> str`: Async query execution

## Security Notes

- Never commit `.env` file to version control
- The `.gitignore` file is configured to prevent accidental commits
- Store your API keys securely

## Generated by AgentOS

Created with [AgentOS](https://github.com/yourusername/agent-os) - Production-grade AI agent framework
"""
        readme_file.write_text(readme_content, encoding="utf-8")

        console.print(format_success(
            f"Exported agent as Python class",
            details={
                "Agent": agent_name,
                "Class": class_name,
                "Folder": str(agent_folder.absolute()),
                "Files": f"{agent_name}_class.py, README.md, requirements.txt, .env.example, .gitignore",
                "Usage": f"from {agent_name}_class import {class_name}",
            }
        ))
        return str(output_file)
    except Exception as e:
        console.print(format_error(f"Failed to write Python file: {e}"))
        return None

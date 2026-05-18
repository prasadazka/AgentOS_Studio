"""
Agent: DataAssist
Generated from YAML config by AgentOS

Setup:
    1. Create a .env file in the same directory with:
       OPENAI_API_KEY=sk-proj-your-key-here

    2. Or set environment variable:
       export OPENAI_API_KEY=sk-proj-your-key-here  # Linux/Mac
       set OPENAI_API_KEY=sk-proj-your-key-here     # Windows

Usage:
    python DataAssist.py "your question here"
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
    """Run DataAssist agent"""

    # Check if API key is available
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Error: OPENAI_API_KEY not found!")
        print("\nPlease set your API key using one of these methods:")
        print("1. Create a .env file: OPENAI_API_KEY=sk-proj-...")
        print("2. Set environment variable: export OPENAI_API_KEY=sk-proj-...")
        print("3. Run: python -c 'import os; os.environ[\"OPENAI_API_KEY\"] = \"sk-...\"; exec(open(\"DataAssist.py\").read())'")
        sys.exit(1)

    # Create agent
    agent = Agent.create(
        name="DataAssist",
        tools=["csv_process", "dataframe_describe", "dataframe_visualize", "dataframe_analyze_folder"],
        model="gpt-4o-mini",
        temperature=0.0,
        prompt=""""""
    )

    # Get query from command line or prompt
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Query: ")

    # Run agent
    print(f"\n[DataAssist] Processing...\n")
    response = agent.run(query)
    print(f"\n[Response]\n{response}\n")


if __name__ == "__main__":
    main()

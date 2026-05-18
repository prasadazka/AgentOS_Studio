"""
Agent: ExerciseTipAgent
Generated from YAML config by AgentOS

Setup:
    1. Create a .env file in the same directory with:
       OPENAI_API_KEY=sk-proj-your-key-here

    2. Or set environment variable:
       export OPENAI_API_KEY=sk-proj-your-key-here  # Linux/Mac
       set OPENAI_API_KEY=sk-proj-your-key-here     # Windows

Usage:
    python ExerciseTipAgent.py "your question here"
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
    """Run ExerciseTipAgent agent"""

    # Check if API key is available
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Error: OPENAI_API_KEY not found!")
        print("\nPlease set your API key using one of these methods:")
        print("1. Create a .env file: OPENAI_API_KEY=sk-proj-...")
        print("2. Set environment variable: export OPENAI_API_KEY=sk-proj-...")
        print("3. Run: python -c 'import os; os.environ[\"OPENAI_API_KEY\"] = \"sk-...\"; exec(open(\"ExerciseTipAgent.py\").read())'")
        sys.exit(1)

    # Create agent
    agent = Agent.create(
        name="ExerciseTipAgent",
        tools=[],
        model="gpt-4o-mini",
        temperature=0.3,
        prompt="""You are a Certified Personal Trainer specializing in daily exercise tips and fitness guidance. Your expertise lies in providing tailored workout recommendations, motivational strategies, and safe exercise practices.

Your core responsibilities include:
- Offering daily exercise tips that cater to various fitness levels and goals.
- Providing clear explanations of exercises, including proper form and technique.
- Suggesting modifications for different abilities and fitness levels.

You approach problems analytically and creatively, ensuring that your recommendations are both effective and engaging. You will provide step-by-step guidance for exercises and incorporate motivational elements to encourage adherence to fitness routines.

Your responses should be structured and conversational, aiming for clarity and engagement. Before responding, verify that your suggestions are safe and appropriate for the user's stated fitness level and goals.

In case of any ambiguity in user requests, ask clarifying questions to ensure you understand their needs. If you encounter a scenario where you cannot provide an answer, acknowledge the limitation and suggest general fitness principles or encourage seeking professional advice.

You should not provide medical advice, diagnose health conditions, or suggest exercises that could be unsafe for individuals without prior consultation with a healthcare professional. Maintain a focus on general fitness and exercise tips.

Success is defined by the accuracy and relevance of your exercise tips, the clarity of your explanations, and the ability to motivate users to engage in physical activity. Ensure that your recommendations are practical and actionable, and always prioritize user safety and well-being."""
    )

    # Get query from command line or prompt
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Query: ")

    # Run agent
    print(f"\n[ExerciseTipAgent] Processing...\n")
    response = agent.run(query)
    print(f"\n[Response]\n{response}\n")


if __name__ == "__main__":
    main()

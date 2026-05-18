"""
Streaming output handler for CLI

Provides live streaming output with Rich formatting.
"""

from typing import Optional, Callable
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


class StreamingOutput:
    """Handle streaming output with live updates"""

    def __init__(self, title: str = "Processing"):
        """
        Initialize streaming output.

        Args:
            title: Title for the streaming panel
        """
        self.title = title
        self.buffer = []
        self.live = None

    def start(self):
        """Start streaming output"""
        spinner = Spinner("dots", text=f"[cyan]{self.title}...", style="cyan")
        self.live = Live(spinner, console=console, refresh_per_second=20)
        self.live.start()

    def update(self, chunk: str):
        """
        Update streaming output with new chunk.

        Args:
            chunk: New text chunk to append
        """
        self.buffer.append(chunk)

        if self.live:
            content = "".join(self.buffer).strip()
            panel = Panel(
                Markdown(content),
                title=f"[bold cyan]{self.title}[/bold cyan]",
                border_style="cyan",
                padding=(0, 1),
                expand=False
            )
            self.live.update(panel)

    def stop(self):
        """Stop streaming output"""
        if self.live:
            self.live.stop()
            self.live = None

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure live display stops immediately"""
        self.stop()
        console.print()  # Add newline to clear any residual output
        return False


def stream_agent_output(
    agent_name: str,
    callback: Callable[[str], None],
) -> StreamingOutput:
    """
    Create streaming output for agent execution.

    Args:
        agent_name: Name of the executing agent
        callback: Callback function for each chunk

    Returns:
        StreamingOutput instance
    """
    return StreamingOutput(title=f"Agent: {agent_name}")
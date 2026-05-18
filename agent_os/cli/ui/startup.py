"""Startup animation and loading indicators for CLI"""

import random
import time
import threading
from contextlib import contextmanager
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text
from rich.align import Align

console = Console()

AGENT_OS_QUOTES = [
    "Building production-grade AI agents with minimal code...",
    "Eliminating 80% of boilerplate in agent development...",
    "Schema-first methodology for reliable data operations...",
    "Smart prompts, optimal temperature, perfect iterations...",
    "From concept to production in minutes, not weeks...",
    "Reusable tools, declarative workflows, enterprise scale...",
    "One framework, many agents, zero vendor lock-in...",
    "Professional AI agents with clear methodology, not chatbots...",
    "Automatic schema discovery across DataFrame and SQL tools...",
    "Error recovery by design, production-ready from day one...",
]

AGENT_OS_ASCII = r"""
   ___                    __  ____  ____
  / _ |___ ____ ___  ___ / /_/ __ \/ __/
 / __ / _ `/ -_) _ \/ _ / __/ /_/ /\ \
/_/ |_\_, /\__/_//_/\___\__/\____/___/
     /___/
"""


def show_startup_animation():
    """Display startup animation with loading spinner and quotes"""
    try:
        # Select random quote
        quote = random.choice(AGENT_OS_QUOTES)

        # Create ASCII art with gradient
        ascii_art = Text(AGENT_OS_ASCII, style="bold cyan")

        # Create panel with quote
        panel_content = Align.center(
            Text.assemble(
                (ascii_art, "\n\n"),
                (quote, "italic dim"),
                ("\n\nInitializing framework...", "dim")
            )
        )

        panel = Panel(
            panel_content,
            border_style="cyan",
            padding=(1, 2)
        )

        # Show with spinner
        with Live(panel, console=console, refresh_per_second=10, transient=True):
            # Simulate realistic loading phases
            phases = [
                ("Loading core modules", 0.3),
                ("Registering tools", 0.4),
                ("Initializing agents", 0.3),
            ]

            for phase_text, duration in phases:
                # Update panel with current phase
                phase_content = Align.center(
                    Text.assemble(
                        (ascii_art, "\n\n"),
                        (quote, "italic dim"),
                        (f"\n\n{phase_text}...", "yellow")
                    )
                )
                panel = Panel(
                    phase_content,
                    border_style="cyan",
                    padding=(1, 2)
                )
                # Small delay for phase
                time.sleep(duration)

    except Exception:
        # If animation fails, just skip it silently
        pass


def show_simple_loading(message: str = "Loading AgentOS..."):
    """Simple loading spinner (fallback for environments without full terminal support)"""
    try:
        with console.status(f"[cyan]{message}[/cyan]", spinner="dots"):
            time.sleep(1.0)
    except Exception:
        # Fallback to plain text
        console.print(f"{message}")


@contextmanager
def startup_animation_context():
    """Context manager that shows animation while work is being done"""
    import sys

    try:
        # Show ASCII art and quote immediately
        quote = random.choice(AGENT_OS_QUOTES)

        # Simple, direct output that works on all platforms
        print("\n")
        print("=" * 70)
        print(AGENT_OS_ASCII)
        print(f"\n{quote}")
        print("\nInitializing AgentOS framework", end="", flush=True)
        sys.stdout.flush()

        # Start a simple dot animation in background
        stop_event = threading.Event()

        def print_dots():
            while not stop_event.is_set():
                print(".", end="", flush=True)
                sys.stdout.flush()
                time.sleep(0.5)

        dot_thread = threading.Thread(target=print_dots, daemon=True)
        dot_thread.start()

        yield

        # Stop animation
        stop_event.set()
        dot_thread.join(timeout=1)
        print("\n")
        print("=" * 70)
        print("\n")

    except Exception:
        yield

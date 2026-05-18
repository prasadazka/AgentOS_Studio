"""
Interactive prompts for CLI

Provides user-friendly interactive prompts using Rich.
"""

from typing import List, Optional
from rich.prompt import Prompt, Confirm
from rich.console import Console

console = Console()


def ask_text(
    prompt: str,
    default: Optional[str] = None,
    password: bool = False,
) -> str:
    """
    Ask user for text input.

    Args:
        prompt: Prompt message
        default: Default value if user presses enter
        password: Whether to hide input (for passwords)

    Returns:
        User input string
    """
    return Prompt.ask(
        f"[cyan]{prompt}[/cyan]",
        default=default,
        password=password,
        console=console,
    )


def ask_confirm(prompt: str, default: bool = False) -> bool:
    """
    Ask user for yes/no confirmation.

    Args:
        prompt: Prompt message
        default: Default value (True = yes, False = no)

    Returns:
        Boolean confirmation
    """
    return Confirm.ask(
        f"[yellow]{prompt}[/yellow]",
        default=default,
        console=console,
    )


def ask_choice(
    prompt: str,
    choices: List[str],
    default: Optional[str] = None,
) -> str:
    """
    Ask user to choose from a list of options.

    Args:
        prompt: Prompt message
        choices: List of valid choices
        default: Default choice

    Returns:
        Selected choice
    """
    return Prompt.ask(
        f"[cyan]{prompt}[/cyan]",
        choices=choices,
        default=default,
        console=console,
    )


def ask_int(
    prompt: str,
    default: Optional[int] = None,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    """
    Ask user for integer input.

    Args:
        prompt: Prompt message
        default: Default value
        min_value: Minimum allowed value
        max_value: Maximum allowed value

    Returns:
        Integer value
    """
    while True:
        response = Prompt.ask(
            f"[cyan]{prompt}[/cyan]",
            default=str(default) if default is not None else None,
            console=console,
        )

        try:
            value = int(response)

            if min_value is not None and value < min_value:
                console.print(f"[red]Value must be >= {min_value}[/red]")
                continue

            if max_value is not None and value > max_value:
                console.print(f"[red]Value must be <= {max_value}[/red]")
                continue

            return value

        except ValueError:
            console.print(f"[red]Please enter a valid integer[/red]")


def ask_float(
    prompt: str,
    default: Optional[float] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    """
    Ask user for float input.

    Args:
        prompt: Prompt message
        default: Default value
        min_value: Minimum allowed value
        max_value: Maximum allowed value

    Returns:
        Float value
    """
    while True:
        response = Prompt.ask(
            f"[cyan]{prompt}[/cyan]",
            default=str(default) if default is not None else None,
            console=console,
        )

        try:
            value = float(response)

            if min_value is not None and value < min_value:
                console.print(f"[red]Value must be >= {min_value}[/red]")
                continue

            if max_value is not None and value > max_value:
                console.print(f"[red]Value must be <= {max_value}[/red]")
                continue

            return value

        except ValueError:
            console.print(f"[red]Please enter a valid number[/red]")


def ask_list(
    prompt: str,
    separator: str = ",",
    min_items: int = 0,
) -> List[str]:
    """
    Ask user for a list of items.

    Args:
        prompt: Prompt message
        separator: Character to split on (default: comma)
        min_items: Minimum number of items required

    Returns:
        List of strings
    """
    while True:
        response = Prompt.ask(
            f"[cyan]{prompt}[/cyan] (separate with '{separator}')",
            console=console,
        )

        items = [item.strip() for item in response.split(separator) if item.strip()]

        if len(items) < min_items:
            console.print(f"[red]Please provide at least {min_items} item(s)[/red]")
            continue

        return items

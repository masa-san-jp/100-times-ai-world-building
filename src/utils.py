"""
Utility Functions Module
Helper functions for configuration, data conversion, and display
"""

import yaml
import json
from pathlib import Path
from typing import Dict, Any, Union, Optional
from loguru import logger


def load_config(config_path: str = "config/ollama_config.yaml") -> Dict[str, Any]:
    """
    Load configuration from YAML file

    Args:
        config_path: Path to configuration file

    Returns:
        Configuration dictionary
    """
    try:
        config_file = Path(config_path)
        if not config_file.exists():
            logger.error(f"Configuration file not found: {config_path}")
            return {}

        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        logger.info(f"Loaded configuration from {config_path}")
        return config

    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        return {}


def data_to_markdown(data: Union[Dict, list, Any], indent: int = 0) -> str:
    """
    Convert Python dict/list to Markdown list format

    Args:
        data: Data to convert (dict, list, or primitive)
        indent: Current indentation level

    Returns:
        Markdown-formatted string
    """
    indent_str = "  " * indent
    lines = []

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{indent_str}- **{key}**:")
                lines.append(data_to_markdown(value, indent + 1))
            else:
                lines.append(f"{indent_str}- **{key}**: {value}")

    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, (dict, list)):
                lines.append(f"{indent_str}- [{i}]:")
                lines.append(data_to_markdown(item, indent + 1))
            else:
                lines.append(f"{indent_str}- [{i}] {item}")

    else:
        lines.append(f"{indent_str}{data}")

    return "\n".join(lines)


def rich_print(content: str, as_markdown: bool = True) -> None:
    """
    Print content in Jupyter notebook with rich formatting

    Args:
        content: Content to display
        as_markdown: Whether to render as Markdown (True) or plain text (False)
    """
    try:
        from IPython.display import display, Markdown

        if as_markdown:
            display(Markdown(content))
        else:
            print(content)

    except ImportError:
        # Not in Jupyter environment, fallback to print
        print(content)


def dict_to_yaml(data: Dict[str, Any]) -> str:
    """
    Convert dictionary to YAML string

    Args:
        data: Dictionary to convert

    Returns:
        YAML-formatted string
    """
    try:
        return yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    except Exception as e:
        logger.error(f"Error converting dict to YAML: {e}")
        return str(data)


def yaml_to_dict(yaml_str: str) -> Optional[Dict[str, Any]]:
    """
    Convert YAML string to dictionary

    Args:
        yaml_str: YAML string to parse

    Returns:
        Parsed dictionary, or None on error
    """
    try:
        return yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML: {e}")
        return None


def save_yaml(data: Dict[str, Any], filepath: str) -> bool:
    """
    Save dictionary to YAML file

    Args:
        data: Data to save
        filepath: Output file path

    Returns:
        True if successful, False otherwise
    """
    try:
        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

        logger.info(f"Saved YAML to {filepath}")
        return True

    except Exception as e:
        logger.error(f"Error saving YAML to {filepath}: {e}")
        return False


def load_yaml(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Load YAML file

    Args:
        filepath: Path to YAML file

    Returns:
        Parsed dictionary, or None on error
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        logger.info(f"Loaded YAML from {filepath}")
        return data

    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML from {filepath}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading YAML from {filepath}: {e}")
        return None


def save_text(content: str, filepath: str) -> bool:
    """
    Save text content to file

    Args:
        content: Text content to save
        filepath: Output file path

    Returns:
        True if successful, False otherwise
    """
    try:
        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Saved text to {filepath}")
        return True

    except Exception as e:
        logger.error(f"Error saving text to {filepath}: {e}")
        return False


def load_text(filepath: str) -> Optional[str]:
    """
    Load text file

    Args:
        filepath: Path to text file

    Returns:
        File content, or None on error
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        logger.info(f"Loaded text from {filepath}")
        return content

    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
        return None
    except Exception as e:
        logger.error(f"Error loading text from {filepath}: {e}")
        return None


def format_prompt(template: str, **kwargs) -> str:
    """
    Format prompt template with variables

    Args:
        template: Prompt template string with {variable} placeholders
        **kwargs: Variables to substitute

    Returns:
        Formatted prompt string
    """
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.error(f"Missing template variable: {e}")
        return template
    except Exception as e:
        logger.error(f"Error formatting prompt: {e}")
        return template


def truncate_text(text: str, max_length: int = 1000, suffix: str = "...") -> str:
    """
    Truncate text to maximum length

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix


def estimate_tokens(text: str) -> int:
    """
    Roughly estimate token count
    (This is a simple approximation: ~4 chars per token for Japanese)

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    # Simple heuristic: ~4 characters per token for Japanese text
    return len(text) // 4


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    console: bool = True,
) -> None:
    """
    Setup logging configuration

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        console: Whether to log to console
    """
    from loguru import logger
    import sys

    # Remove default handler
    logger.remove()

    # Add console handler
    if console:
        logger.add(
            sys.stdout,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        )

    # Add file handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_file,
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation="10 MB",
            retention="7 days",
        )

    logger.info(f"Logging setup complete (level: {log_level})")

import math
from fastmcp import FastMCP

mcp = FastMCP("Calculator")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers together."""
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide a by b. Raises an error if b is zero."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


@mcp.tool()
def power(base: float, exponent: float) -> float:
    """Raise base to the given exponent."""
    return base ** exponent


@mcp.tool()
def sqrt(n: float) -> float:
    """Calculate the square root of a number. Raises an error if n is negative."""
    if n < 0:
        raise ValueError("Cannot take square root of a negative number")
    return math.sqrt(n)


@mcp.tool()
def modulo(a: float, b: float) -> float:
    """Return the remainder when a is divided by b."""
    if b == 0:
        raise ValueError("Cannot perform modulo with divisor zero")
    return a % b


@mcp.tool()
def absolute(n: float) -> float:
    """Return the absolute value of a number."""
    return abs(n)


@mcp.tool()
def floor(n: float) -> int:
    """Return the largest integer less than or equal to n."""
    return math.floor(n)


@mcp.tool()
def ceil(n: float) -> int:
    """Return the smallest integer greater than or equal to n."""
    return math.ceil(n)


if __name__ == "__main__":
    mcp.run(transport="sse")

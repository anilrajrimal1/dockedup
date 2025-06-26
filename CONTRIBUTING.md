# Contributing to DockedUp

First off, thank you for considering contributing! It's people like you that make open source such a great community. We welcome any form of contribution, from reporting bugs and suggesting features to submitting pull requests.

## How Can I Contribute?

### Reporting Bugs

If you find a bug, please ensure it hasn't already been reported by searching the [GitHub Issues](https://github.com/anilrajrimal1/dockedup/issues).

If you're unable to find an open issue addressing the problem, [open a new one](https://github.com/anilrajrimal1/dockedup/issues/new). Be sure to include:
-   A **clear and descriptive title**.
-   A detailed description of the bug, including **steps to reproduce it**.
-   Your **operating system**, **Python version**, and **Docker version**.
-   Any **error messages** or tracebacks you encountered.

### Suggesting Enhancements

We are always looking for suggestions to make DockedUp better! You can submit an enhancement suggestion by [opening a new issue](https://github.com/anilrajrimal1/dockedup/issues/new). Please include:
-   A clear and descriptive title.
-   A step-by-step description of the suggested enhancement in as much detail as possible.
-   Explain **why** this enhancement would be useful. What problem does it solve?

### Pull Request Process

Ready to contribute code? Here’s how to set up `DockedUp` for local development.

1.  **Fork the repository** on GitHub.
2.  **Clone your fork** locally:
    ```bash
    git clone https://github.com/your-fork-username/dockedup.git
    cd dockedup
    ```
3.  **Install dependencies** using Poetry:
    ```bash
    poetry install
    ```
4.  **Create a feature branch** from `main`:
    ```bash
    git checkout -b feature/my-amazing-feature
    ```
5.  **Make your changes.** Add your code and any necessary tests.
6.  **Run tests** to ensure nothing has broken:
    ```bash
    poetry run pytest
    ```
7.  **Commit your changes** with a clear and descriptive commit message.
8.  **Push your branch** to your fork on GitHub:
    ```bash
    git push origin feature/my-amazing-feature
    ```
9.  **Open a Pull Request** to the `main` branch of the original `dockedup` repository. Provide a clear description of the changes you've made.

## Code of Conduct

To ensure a welcoming and inclusive environment, we expect all contributors to be respectful and considerate in all their interactions.

We look forward to your contributions!
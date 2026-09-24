# Contributing to Dictionary Web Scraping Machine

Thank you for your interest in contributing to this project!

## GitHub Flow
We strictly follow the **GitHub Flow** for our development process.

1. **Branching**: Always create a new branch from `main` or `master` for your work.
   ```bash
   git checkout -b type/your-feature-name
   ```
2. **Developing**: Make your changes and write tests. Ensure you run the test suite locally.
   ```bash
   pytest
   ```
3. **Committing**: We use **Conventional Commits** for all commit messages. This helps us generate changelogs and version tags automatically.
   Format:
   ```
   <type>(<scope>): <subject>
   ```
   Allowed types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `style`, `ci`, `perf`.
   Example:
   ```bash
   git commit -m "feat(dictionary): add support for multiple languages"
   ```
4. **Pull Request**: Push your branch and open a Pull Request. Use the provided PR template.
5. **Code Review**: A Tech Lead or maintainer will review your code.
6. **Merge**: Once approved and CI passes, your PR will be merged via "Squash and Merge".

## Local Environment Setup
To set up your local development environment:
1. Create a virtual environment: `python3 -m venv .venv`
2. Activate it: `source .venv/bin/activate` (or `.venv\Scripts\activate` on Windows)
3. Install dependencies: `pip install -r requirements-dev.txt`
4. Install pre-commit hooks: `pre-commit install`

Happy coding!

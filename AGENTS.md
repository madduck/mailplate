## Product

This is a CLI application that merges an RFC5322 email draft with a Profile to create a new draft with that Profile applied, in-place or on `stdout` if acting like a filter. A Profile defines aspects of an outgoing Email, such as specific headers and their content, parts of the body, and the mail signature.

## Constraints

- Never install any tool without approval.
- Never read, write, list, or otherwise access files or directories outside the project hierarchy, even for debugging or investigation. Assume all external state is off-limits and irrelevant. If a test or behavior depends on something outside the tree, make the test hermetic instead of inspecting the external cause. The only exception is that you may read the files provided by Pi itself, and if you are convinced you should be allowed, e.g. to read the project's own configuration/state files. In that case, however, obtain my approval first.
- Don't use blocking I/O inside `async` functions.

## Stack

- Python3 and its `email` package
- Click for the CLI

## Project Setup and Management

- Use the latest Python and the newest syntax, but do not import from `__future__` without approval.
- Dependency management: `uv` and `pyproject.toml`. Never use `pip` or a `requirements.txt` file.
- Add a dependency with `uv add <package>`. Never use `uv pip`.
- Make sure that `./$PACKAGENAME/_version.py` provides the package's version information from the build system / Git. This file should not be tracked in Git.
- Set up `./$PACKAGENAME/__init__.py` to export the full version string as `VERSION`, gracefully handling the situation wherein the file does not (yet) exist by setting the version string to `None`.
- Use the exported version string for the output when the CLI is invoked with `--version`.

## Project Structure

- The project lies under `./$PACKAGENAME`.
- `./$PACKAGENAME/cli.py` holds the CLI app.
- Auxiliary classes and helpers should go into sibling files.
- Put tests in `./tests`.

## Ignore

Treat everything in `.gitignore` as off-limits to read or edit. On top of
that, never open:

- Secrets and `.env` files
- Large data files unrelated to the current task
- Vendored or generated code

## Commands

- Run: `uv run`
- Install: `uv install`
- Unit tests: `uv run pytest`
- Type check: `uv run mypy`
- Lint: `uv run ruff`
- Security check: `uv run bandit -c pyproject.toml`
- Production build: `uv build`

## Coding Conventions

- Use existing error classes as much as possible.
- Try not to reinvent wheels, but ask before adding any external dependency.
- Use type hinting consistently and everywhere, including return types.
- Stick to Ruff formatting.
- Use `pathlib` for path management. Don't use `os.path`.
- Prefer f-strings over `str.format()` or `%` formatting.
- Follow EAFP: handle exceptions rather than checking conditions up front.
- When importing from within the same module, always use relative imports.
- Every function should have a Google-style Docstring.
- Embrace idiomatic Python like comprehensions, generators, and decorators.
- Prefer module-level imports over inline imports, unless there is a good reason
  and I approve.
- Write a comment for every assumption you make.
- When code gets more complex, interlace with human-readable commenting.
- Make all strings easily translatable to other languages using standard tools.

## Code checkers

- Include `ruff` and configure it using `pyproject.toml`;
  - Prefer lint rules D211 over D203 and D213 over D212.
  - Select test PLC0415 but ignore it for `tests/**`.
- Include `mypy` in strict mode and configure it using `pyproject.toml`. Set `warn_unreachable`, and configure an override `ignore_missing_imports = true` for module `ipdb`.
- Include `coverage`, configure it to test branch coverage, and with:
  
  ```
  exclude_also = [
    'def __repr__',
    'if TYPE_CHECKING:',
    'class .*\bProtocol\):',
    '@overload',
    '@(abc\.)?abstractmethod',
    'raise NotImplementedError',
    'raise AssertionError',
  ]
  ```

- Include `bandit`. Configure it to skip warning about assertions for all test files.

## Testing

- Consistent red/green testing.
- Aim for 100% line coverage.
- Keep existing tests intact, and fix the code to make them pass.
- Add or update tests for changed public behavior.
- Prefer behavior-based assertions over private implementation details.
- Use deterministic fixtures.
- Run affected tests before the full suite.
- Report any test that could not be executed.
- Never comment out a failing test, but use `pytest.mark.xfail`.
- Set up `pytest` with the following basic flags:
  - `-ra`.
  - `--pdbcls=IPython.terminal.debugger:TerminalPdb`.
- Set up `pytest-cov` to test coverage. Only report on incomplete coverage.
- Set up `pytest-ruff` to test `ruff-format` with `lint.ignore` set to I001, F401 and F841.

## Git Workflow

- Every source file is tracked in Git.
- Never track a generated file without approval.
- `.gitignore` is the source of truth. You need my explicit approval to edit this file each time.
- You have my approval to make sure `.gitignore` contains the following exclusions:
  - `.venv`
  - `.envrc`
  - `.direnv`
  - `__pycache__`
  -`.coverage`
  -`.egg-info`
  -`*_cache`
- Do not merge, or force-push without approval.
- Don't commit to `main` or push without being asked.
- Branch from `main` as `feature/<name>`.
- Make frequent, small commits, keeping contents logically together. Include your thinking in the commit messages.
- Do not use Conventional Commits; Use scope-prefixed commit messages instead.
- Do not include unrelated formatting changes.
- Keep migrations and generated files in the same change as the code that requires them.
- Summarise user-visible behavior and validation in a final commit message preparing a PR.
- Use `pre-commit` to enforce `mypy`, `ruff`, and `bandit`.
- Make sure `mypy`'s pre-commit configuration includes all necessary additional dependencies.

## Quality Gates

A task is done only when Docstrings are updated, and all of these pass:

- `uv run ruff format` leaves the code unchanged.
- `uv run ruff check` reports no errors.
- `uv run mypy .` reports no errors.
- `uv run pytest` passes.
- `uv run bandit -c pyproject.toml -r .` passes.

## Completion Report

After completing a task, report:

- Summary of the behavior changed
- Modified files
- Important implementation decisions
- Commands executed
- Test and build results
- Acceptance criteria status
- Assumptions
- Known limitations
- Remaining risks

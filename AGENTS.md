# Working in this repository

- Be concise and pragmatic. Cite evidence, verify claims directly, and prefer maintainable designs.
- Run all routine GUI tests in the background. Never show, raise, maximize, or activate test windows on the user's desktop; never send OS keyboard/mouse input or change the user's focus.
- Use the background protection in `tests/gui_test_support.py`. Keep it enabled in test subprocesses too. Transparent or off-screen foreground windows are not an acceptable substitute.
- Use `python -B -m unittest discover -s tests -t . -v` for discovery from the repository root. The explicit top-level directory loads `tests/__init__.py` and installs the guard before importing any test modules.
- Native focus, visible hit-testing, screenshot, and manual preview checks require an explicit user request for that foreground session. A general request to audit/test the GUI is not permission. Otherwise skip those checks and report their coverage separately; do not enable the foreground opt-in automatically.
- Keep this policy when adding tests or changing test infrastructure. Do not change the production app's normal window behavior to accommodate tests.

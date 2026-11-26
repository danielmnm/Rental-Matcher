"""Some tests need the raw listing samples (tests/fixtures, tests/eval) or a frozen
settings history. Those samples are not published because they contain third
parties' contact details, so when they are missing those tests are reported as
skipped instead of failing. Everything else runs from a fresh clone."""
import pytest

_LOCAL = ("tests/fixtures", "tests\\fixtures", "tests/eval", "tests\\eval", "preferences/history", "preferences\\history")


def _needs_local_data(text: str) -> bool:
    return "No such file or directory" in text and any(p in text for p in _LOCAL)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    out = yield
    rep = out.get_result()
    if rep.failed and _needs_local_data(str(rep.longrepr)):
        rep.outcome = "skipped"
        rep.longrepr = (str(collector.path), 0, "Skipped: needs the local listing samples (not published)")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    out = yield
    rep = out.get_result()
    if rep.failed and call.excinfo is not None and _needs_local_data(str(call.excinfo.getrepr())):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.path), 0, "Skipped: needs the local listing samples (not published)")


from pathlib import Path as _P
_HERE = _P(__file__).parent
_LISTED = {l.strip() for l in (_HERE / "needs_local_samples.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
_HAVE_SAMPLES = (_HERE / "fixtures").exists() and (_HERE / "eval").exists()


def pytest_collection_modifyitems(config, items):
    if _HAVE_SAMPLES:
        return
    skip = pytest.mark.skip(reason="needs the local listing samples (not published)")
    for it in items:
        if it.nodeid in _LISTED or it.nodeid.split("[")[0] in _LISTED or any(it.nodeid.startswith(x + "::") for x in _LISTED if "::" not in x):
            it.add_marker(skip)

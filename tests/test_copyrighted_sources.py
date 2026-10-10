def test_copyrighted_sources_global_in_jinja_env():
    from jinja2 import BaseLoader
    from app.jinja_setup import make_env
    env = make_env(BaseLoader())
    assert "copyrighted_sources" in env.globals
    cs = env.globals["copyrighted_sources"]
    for source in (
        "iso15926", "iso14224", "cfihos", "isa5_1",
        "posc_caesar", "slb_glossary", "onepetro_glossary", "dexpi", "ppdm",
    ):
        assert source in cs, f"{source} should be in COPYRIGHTED_SOURCES"

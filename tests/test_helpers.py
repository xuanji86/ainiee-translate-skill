from ainiee_translate.helpers import normalize_apostrophes, latin_boundary_search, has_cjk

def test_normalize_apostrophes_folds_curly_and_modifier():
    # U+2019 right single quote, U+02BC modifier letter apostrophe, U+FF07 fullwidth
    assert normalize_apostrophes("Da'ren") == "Da'ren"
    assert normalize_apostrophes("TʼRel") == "T'Rel"
    assert normalize_apostrophes("Vikr＇l") == "Vikr'l"

def test_latin_boundary_search_matches_in_cjk_context():
    assert latin_boundary_search("Bashir", "Julian·Bashir早已见惯") is not None
    # must NOT match inside a larger latin word
    assert latin_boundary_search("Ro", "Korin") is None

def test_has_cjk():
    assert has_cjk("科林") is True
    assert has_cjk("Korin") is False

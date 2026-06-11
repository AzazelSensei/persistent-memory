from persistent_memory.query_expansion import expand_query


def test_expands_known_synonym():
    out = expand_query("login olmadan indir")
    assert "giris" in out or "giriş" in out


def test_passes_through_unknown_terms():
    out = expand_query("nginx vhost")
    assert "nginx" in out and "vhost" in out


def test_idempotent_when_already_expanded():
    once = expand_query("reels indir")
    twice = expand_query(once)
    assert set(twice.split()) >= set(once.split())


def test_expands_raw_turkish_form():
    out = expand_query("giriş yapmadan video çekmek")
    tokens = set(out.split())
    assert "login" in tokens
    assert "reels" in tokens


def test_empty_query_stays_empty():
    assert expand_query("") == ""


def test_expands_uppercase_turkish_form():
    out = expand_query("GİRİŞ yapmadan")
    assert "login" in set(out.split())


def test_expands_token_with_trailing_punctuation():
    out = expand_query("login, olmadan")
    assert "giris" in set(out.split())

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))

from verify_service import _quality_checks_for_row


def _run(**kwargs):
    defaults = dict(
        cluster_label="pump",
        genus="momentum-transfer device",
        nl_definition_en="A pump is a momentum-transfer device that increases liquid pressure.",
        nl_definition_pt="Uma bomba é um dispositivo de transferência de quantidade de movimento.",
        semiformal_axiom="Every pump bears exactly one pumping function.",
        label_pt="bomba",
    )
    defaults.update(kwargs)
    return _quality_checks_for_row(**defaults)


def ids(issues):
    return [i["check_id"] for i in issues]


# ── Check A ──────────────────────────────────────────────────────────────────

def test_check_A_passes_when_genus_in_definition():
    assert "A" not in ids(_run())


def test_check_A_fails_when_genus_absent():
    issues = _run(nl_definition_en="A pump is an artifact that moves fluids.")
    assert "A" in ids(issues)


def test_check_A_is_case_insensitive():
    issues = _run(genus="Momentum-Transfer Device",
                  nl_definition_en="A pump is a momentum-transfer device that increases pressure.")
    assert "A" not in ids(issues)


def test_check_A_passes_when_genus_is_camelcase_of_words_in_definition():
    issues = _run(genus="MaterialArtifact",
                  nl_definition_en="An instrument is a material artifact that performs measurement.")
    assert "A" not in ids(issues)


def test_check_A_skipped_when_genus_empty():
    issues = _run(genus="")
    assert "A" not in ids(issues)


# ── Check B ──────────────────────────────────────────────────────────────────

def test_check_B_en_fails_when_empty():
    assert "B_en" in ids(_run(nl_definition_en=""))


def test_check_B_en_fails_when_whitespace_only():
    assert "B_en" in ids(_run(nl_definition_en="   "))


def test_check_B_pt_fails_when_empty():
    assert "B_pt" in ids(_run(nl_definition_pt=""))


def test_check_B_passes_when_both_filled():
    issues = _run()
    assert "B_en" not in ids(issues)
    assert "B_pt" not in ids(issues)


# ── Check C ──────────────────────────────────────────────────────────────────

def test_check_C_fails_when_semiformal_empty():
    assert "C" in ids(_run(semiformal_axiom=""))


def test_check_C_passes_when_filled():
    assert "C" not in ids(_run())


# ── Check D ──────────────────────────────────────────────────────────────────

def test_check_D_fails_when_label_pt_empty():
    assert "D" in ids(_run(label_pt=""))


def test_check_D_passes_when_filled():
    assert "D" not in ids(_run())


# ── Check G ──────────────────────────────────────────────────────────────────

def test_check_G_fails_when_definition_is_just_the_label():
    issues = _run(cluster_label="pump", nl_definition_en="pump")
    assert "G" in ids(issues)


def test_check_G_fails_when_too_short_after_stripping_label():
    issues = _run(cluster_label="pump", nl_definition_en="pump is good")
    assert "G" in ids(issues)


def test_check_G_passes_when_meaningful_differentia():
    assert "G" not in ids(_run())


def test_check_G_passes_when_definition_does_not_start_with_label():
    # Definition that doesn't start with label but is long enough
    issues = _run(cluster_label="pump",
                  nl_definition_en="A momentum-transfer device whose designed function is to increase liquid pressure.")
    assert "G" not in ids(issues)


def test_all_pass_on_well_formed_entry():
    assert ids(_run()) == []

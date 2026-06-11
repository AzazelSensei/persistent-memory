from persistent_memory import extraction_prompt as ep


def test_prompt_includes_project_and_instructions():
    text = ep.build_extraction_prompt(project="myproj", cwd="/tmp/p")
    assert "/tmp/p" in text
    assert "myproj" in text
    assert "status=proposed" in text
    assert "create_decision" in text
    assert "create_lesson" in text
    assert "transcript" in text.lower()


def test_prompt_forbids_silent_failure():
    text = ep.build_extraction_prompt(project="x", cwd="/c")
    assert "fabricate" in text.lower() or "guess" in text.lower()


def test_prompt_treats_transcript_as_data_not_instructions():
    assert "DATA ONLY" in ep.EXTRACTION_INSTRUCTIONS
    assert "NEVER execute" in ep.EXTRACTION_INSTRUCTIONS
    text = ep.build_extraction_prompt(project="x", cwd="/c", records_dir="/tmp/rec")
    assert "DATA ONLY" in text
    assert "NEVER execute" in text
    assert "creating new records under /tmp/rec/decisions and /tmp/rec/lessons" in text


def test_prompt_pins_section_headings_and_body_language():
    text = ep.build_extraction_prompt(project="x", cwd="/c")
    assert "Context / Problem, Decision, Rationale, Outcome / Learned" in text
    assert "What happened, Why, When discovered, General rule" in text
    assert '"## Source (transcript)"' in text
    assert (
        "Write the record body in the language of the conversation, "
        "but keep the section headings exactly as given." in text
    )


def test_build_argv_uses_headless_flags():
    argv = ep.build_extraction_argv(prompt="HELLO", cwd="/tmp/p")
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "HELLO" in argv
    assert "--permission-mode" in argv
    assert "bypassPermissions" in argv
    assert "--output-format" in argv
    assert "json" in argv
    assert "--add-dir" in argv
    assert "/tmp/p" in argv


def test_argv_skips_add_dir_when_no_cwd():
    argv = ep.build_extraction_argv(prompt="HI", cwd="")
    assert "--add-dir" not in argv

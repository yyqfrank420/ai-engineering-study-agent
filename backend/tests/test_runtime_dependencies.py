from pathlib import Path


def test_es256_backend_is_an_explicit_production_dependency():
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements = {
        line.partition("==")[0].lower(): line
        for line in requirements_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith(("#", "-"))
    }

    assert requirements["pyjwt"].startswith("PyJWT==")
    assert requirements["cryptography"].startswith("cryptography==")


def test_langgraph_is_an_explicit_pinned_runtime_dependency():
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements = requirements_path.read_text(encoding="utf-8").splitlines()

    assert "langgraph==1.2.9" in requirements
    assert "uvicorn[standard]==0.49.0" in requirements

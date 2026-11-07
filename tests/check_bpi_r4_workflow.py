"""Run with python3 tests/check_bpi_r4_workflow.py (no network or dependencies)."""
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import textwrap

workflow = Path(__file__).resolve().parents[1] / ".github/workflows/bpi-r4-main_router-self-hosted.yaml"
source = workflow.read_text()


def step(name):
    body = source.split(f"      - name: {name}\n", 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(body.split("        run: ", 1)[1].removeprefix("|\n"))


assert "ref: ${{ needs.check_commits.outputs.latest_commit_sha }}" in source
assert "ref: ${{ github.sha }}\n          path: builder" in source
assert "refs/heads/nhp/configs/" not in re.sub(r"^\s*#.*$", "", source, flags=re.M)
assert "git^124c9f7983dcd6fddf46d3e863fc67853017c4fd" in source
assert source.index("- name: Record config and final image checksums") < source.index("- name: Package output")

for match in re.finditer(r"^        run: \|\n((?:          .*\n|\s*\n)+)", source, re.M):
    script = re.sub(r"\$\{\{.*?\}\}", "CHECK_VALUE", textwrap.dedent(match[1]))
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)

with tempfile.TemporaryDirectory(prefix="bpi-r4-workflow-") as directory:
    root = Path(directory)
    output = root / "bin/targets/mediatek/filogic"
    output.mkdir(parents=True)
    (root / ".config").write_text("CONFIG_TARGET_mediatek=y\n")
    image = output / "openwrt-bpi-r4-sdcard.img.gz"
    image.write_bytes(b"image after BL2 replacement")
    (output / "sha256sums").write_text("stale checksums\n")
    for name in ["Record config and final image checksums", "Package output"]:
        subprocess.run(["bash", "-e", "-o", "pipefail", "-c", step(name)], cwd=root, check=True)
    with tarfile.open(root / "bpi_r4-images.tar") as archive:
        config = archive.extractfile("bin/targets/mediatek/filogic/config-full")
        assert config is not None
        assert config.read() == (root / ".config").read_bytes()
    image.write_bytes(b"corrupt image")
    result = subprocess.run(["sha256sum", "-c", "sha256sums"], cwd=output, capture_output=True)
    assert result.returncode != 0, "A changed image must fail checksum verification"

print("PASS: shell syntax, pinned checkouts, packaged config and final image checksums")

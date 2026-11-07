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
assert "cat builder/configs/common/openssl-accel >> .config" in source
assert "delete_tag_pattern: ${{ env.RELEASE_PREFIX }}-${{ env.REMOTE_BRANCH }}-" in source
assert "${{ github.run_id }}-${{ github.run_attempt }}" in source
assert 'make download -j"$(nproc)" || make download -j1 V=s' in source

profile = (workflow.parents[2] / "configs/common/main-router").read_text()
for package in ["block-mount", "e2fsprogs", "zapret2", "luci-app-zapret2", "dnsmasq-full", "netbird", "kmod-usb-net-cdc-mbim"]:
    assert f"CONFIG_PACKAGE_{package}=y" in profile, f"Custom package lost during merge: {package}"
assert "CONFIG_LUCI_LANG_ru=y" in profile
for obsolete in ["CONFIG_PACKAGE_wifi-scripts=y", "CONFIG_ALL_KMODS=y", "CONFIG_ALL_NONSHARED=y", "CONGIG_"]:
    assert obsolete not in profile
openssl = (workflow.parents[2] / "configs/common/openssl").read_text()
assert "CONFIG_PACKAGE_wpad-openssl=y" in openssl
assert "CONFIG_PACKAGE_kmod-cryptodev=y" not in openssl
assert "CONFIG_OPENSSL_ENGINE_BUILTIN_DEVCRYPTO=y" not in openssl
for name in ["cudy_ap3000.yaml", "u6lite.yaml"]:
    # The shared parents profile no longer selects full wpad on its own.
    assert "        common/mbedtls\n" in (workflow.parent / name).read_text()
for name in ["bpi-r4-main_router.yaml", "_build-openwrt.yml"]:
    assert step("Add ISL download mirror").strip() in (workflow.parent / name).read_text()

for match in re.finditer(r"^        run: \|\n((?:          .*\n|\s*\n)+)", source, re.M):
    script = re.sub(r"\$\{\{.*?\}\}", "CHECK_VALUE", textwrap.dedent(match[1]))
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)

with tempfile.TemporaryDirectory(prefix="bpi-r4-workflow-") as directory:
    root = Path(directory)
    output = root / "bin/targets/mediatek/filogic"
    output.mkdir(parents=True)
    isl = root / "tools/isl/Makefile"
    isl.parent.mkdir(parents=True)
    original = "PKG_VERSION:=0.28\nPKG_SOURCE_URL:=https://libisl.sourceforge.io/\nPKG_HASH:=unchanged\n"
    isl.write_text(original)
    for _ in range(2):
        subprocess.run(["bash", "-e", "-c", step("Add ISL download mirror")], cwd=root, check=True)
    assert isl.read_text() == original.replace("PKG_SOURCE_URL:=", "PKG_SOURCE_URL:=https://downloads.sourceforge.net/project/libisl ")
    (root / ".config").write_text("CONFIG_PACKAGE_example=m\nCONFIG_PACKAGE_libustream-mbedtls=m\nCONFIG_OTHER=y\n")
    subprocess.run(["bash", "-e", "-c", step("Remove packages that are marked as modules")], cwd=root, check=True)
    assert (root / ".config").read_text() == "# CONFIG_PACKAGE_example is not set\nCONFIG_PACKAGE_libustream-mbedtls=m\nCONFIG_OTHER=y\n"
    (root / ".config").write_text("CONFIG_TARGET_mediatek=y\n")
    for excluded in ["packages", "kernels"]:
        (output / excluded).mkdir()
        (output / excluded / "excluded.bin").write_bytes(b"not a firmware release asset")
    image = output / "openwrt-bpi-r4-sdcard.img.gz"
    image.write_bytes(b"image after BL2 replacement")
    (output / "sha256sums").write_text("stale checksums\n")
    for name in ["Record config and final image checksums", "Package output"]:
        subprocess.run(["bash", "-e", "-o", "pipefail", "-c", step(name)], cwd=root, check=True)
    with tarfile.open(root / "bpi_r4-images.tar") as archive:
        config = archive.extractfile("bin/targets/mediatek/filogic/config-full")
        assert config is not None
        assert config.read() == (root / ".config").read_bytes()
        assert not any("/packages/" in name or "/kernels/" in name for name in archive.getnames())
    image.write_bytes(b"corrupt image")
    result = subprocess.run(["sha256sum", "-c", "sha256sums"], cwd=output, capture_output=True)
    assert result.returncode != 0, "A changed image must fail checksum verification"

print("PASS: shell syntax, pinned checkouts, packaged config and final image checksums")

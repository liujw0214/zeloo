class Zeloo < Formula
  desc "Self-hosted, self-evolving resident AI Agent runtime"
  homepage "https://github.com/your-org/Zeloo"
  url "https://github.com/your-org/Zeloo/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256"
  license "Apache-2.0"

  depends_on "python@3.11"

  # Build-time dependencies for the native FTS5 CJK tokenizer extension
  depends_on "rust" => :build

  resource "root" do
    url "https://files.pythonhosted.org/packages/source/z/zeloo/zeloo-0.1.0-py3-none-any.whl"
    sha256 "PLACEHOLDER_WHL_SHA256"
  end

  resource "cryptography" do
    url "https://files.pythonhosted.org/packages/source/c/cryptography/cryptography-42.0.0.tar.gz"
    sha256 "PLACEHOLDER_CRYPTO_SHA256"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/source/p/pydantic/pydantic-2.5.0.tar.gz"
    sha256 "PLACEHOLDER_PYDANTIC_SHA256"
  end

  def install
    # Build the native Rust extension (FTS5 CJK tokenizer) on demand
    if File.directory?("native/fts5_cjk")
      cd "native/fts5_cjk" do
        system "cargo", "build", "--release"
      end
    end

    # Install the project into a Homebrew-managed virtualenv, wiring in any
    # `resource` wheels declared above as fallback wheels.
    virtualenv_install_with_resources
  end

  def post_install
    # Surface a friendly message and instruct the user on first-run setup.
    ohai "Zeloo has been installed. Run `zeloo doctor` to verify the install"
    ohai "and `zeloo install` to perform first-run workspace initialization."
  end

  test do
    # The CLI entry point must report its version after install.
    assert_match version.to_s, shell_output("#{bin}/zeloo --version")
  end
end

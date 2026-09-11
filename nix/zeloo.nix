{
  pkgs ? import <nixpkgs> { },
  python ? pkgs.python312,
}:

python.pkgs.buildPythonPackage {
  pname = "Zeloo";
  version = "0.1.0";

  src = pkgs.lib.cleanSource ../.;

  format = "pyproject";

  nativeBuildInputs = with pkgs; [
    git
  ];

  propagatedBuildInputs = with python.pkgs; [
    openai
    httpx
    pyyaml
    python-dotenv
    pydantic
    typer
    rich
  ];

  doCheck = false;  # pytest invocation is in checks.nix

  meta = with pkgs.lib; {
    description = "Self-hosted, self-evolving AI agent runtime";
    homepage = "https://github.com/Zeloo/Zeloo";
    license = licenses.asl20;
    maintainers = [ ];
    platforms = platforms.unix;
  };
}
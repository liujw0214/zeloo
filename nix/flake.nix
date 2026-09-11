{
  description = "Zeloo Agent Runtime — flake inputs";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = nixpkgs.legacyPackages.${system}; in {
        packages.Zeloo = pkgs.callPackage ./package.nix { };
        defaultPackage = self.packages.${system}.Zeloo;
        apps.Zeloo = {
          type = "app";
          program = "${self.packages.${system}.Zeloo}/bin/Zeloo";
        };
        devShells.default = import ./shell.nix { inherit pkgs; };
      }
    ) // {
      nixosModules.Zeloo = ./homeManagerModules.nix;
      nixosModules.default = ./configMergeScript.nix;
    };
}

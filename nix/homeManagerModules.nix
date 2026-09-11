{ config, lib, pkgs, ... }:

let
  cfg = config.home.packages.Zeloo;
in
{
  options.home.packages.Zeloo = with lib; {
    enable = mkEnableOption "Zeloo Agent Runtime";

    package = mkOption {
      type = types.package;
      default = pkgs.Zeloo;
      description = "Zeloo package to use";
    };

    profile = mkOption {
      type = types.enum [ "default" "minimal" "research" ];
      default = "default";
      description = "Zeloo runtime profile";
    };

    providers = mkOption {
      type = types.attrsOf types.str;
      default = { };
      example = { openai = "gpt-4o"; anthropic = "claude-3-5-sonnet-latest"; };
      description = "Model provider configurations";
    };

    toolsets = mkOption {
      type = types.listOf types.str;
      default = [ "cli" ];
      description = "Enabled toolset names";
    };

    observability = {
      enable = mkEnableOption "Langfuse observability integration";
      url = mkOption {
        type = types.str;
        default = "";
        description = "Langfuse public URL";
      };
      secretKey = mkOption {
        type = types.str;
        default = "";
        description = "Langfuse secret key";
      };
      publicKey = mkOption {
        type = types.str;
        default = "";
        description = "Langfuse public key";
      };
    };

    workspace = {
      defaultName = mkOption {
        type = types.str;
        default = "default";
        description = "Default workspace name";
      };
      autoCreate = mkEnableOption "auto-create workspace on first run";
    };

    shellAlias = mkOption {
      type = types.bool;
      default = true;
      description = "Add 'Zeloo' shell alias";
    };

    autoStart = mkEnableOption "auto-start daemon on shell login";
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];

    programs.bash.initExtra = lib.mkIf cfg.shellAlias ''
      alias Zeloo="${cfg.package}/bin/Zeloo"
    '';

    xdg.configFile."Zeloo" = {
      source = pkgs.writeText "config.yaml" (lib.generators.toYAML { } {
        profile = cfg.profile;
        toolsets = cfg.toolsets;
        providers = cfg.providers;
        observability = lib.mkIf cfg.observability.enable {
          langfuse = {
            enabled = true;
            publicUrl = cfg.observability.url;
            secretKey = cfg.observability.secretKey;
            publicKey = cfg.observability.publicKey;
          };
        };
      });
    };

    systemd.user.services.Zeloo = lib.mkIf cfg.autoStart {
      Unit = {
        Description = "Zeloo Agent Runtime";
        PartOf = [ "graphical-session.target" ];
      };

      Service = {
        Type = "simple";
        ExecStart = "${cfg.package}/bin/Zeloo run --workspace ${cfg.workspace.defaultName}";
        Restart = "on-failure";
        RestartSec = 5;
        Environment = [ "HOME=%h" ];
      };

      Install.WantedBy = [ "graphical-session.target" ];
    };

    home.activation.Zeloo = lib.mkIf cfg.workspace.autoCreate (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        ${cfg.package}/bin/Zeloo workspace create ${cfg.workspace.defaultName} 2>/dev/null || true
      ''
    );
  };
}

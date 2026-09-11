{ config, lib, pkgs, ... }:

let
  cfg = config.services.Zeloo;
in
{
  options.services.Zeloo = with lib; {
    enable = mkEnableOption "Zeloo Agent Runtime desktop service";

    package = mkOption {
      type = types.package;
      default = pkgs.Zeloo;
      description = "Zeloo package to use";
    };

    user = mkOption {
      type = types.str;
      default = "Zeloo";
      description = "User to run Zeloo as";
    };

    dataDir = mkOption {
      type = types.path;
      default = "\${config.users.users.${cfg.user}.home}/.Zeloo";
      description = "Data directory for Zeloo runtime state";
    };

    extraArgs = mkOption {
      type = types.listOf types.str;
      default = [];
      example = [ "--verbose" "--profile", "work" ];
      description = "Additional arguments to pass to Zeloo daemon";
    };

    openPorts = mkOption {
      type = types.bool;
      default = false;
      description = "Open firewall ports for Zeloo API (7860, 8765, 9112)";
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.${cfg.user} = lib.mkIf (!lib.pathExists "\${config.users.users.${cfg.user}.home}") {
      isNormalUser = true;
      home = "/var/lib/Zeloo";
      description = "Zeloo Agent Runtime user";
      group = "Zeloo";
    };

    users.groups.Zeloo = {};

    systemd.user.services.Zeloo = {
      Unit = {
        Description = "Zeloo Agent Runtime Daemon";
        After = [ "network.target" "sqlite.service" ];
        PartOf = [ "graphical-session.target" ];
      };

      Service = {
        Type = "simple";
        ExecStart = "${cfg.package}/bin/Zeloo run ${lib.concatStringsSep " " cfg.extraArgs}";
        Restart = "on-failure";
        RestartSec = 5;
        WorkingDirectory = cfg.dataDir;
        Environment = [
          "HOME=%h"
          "zeloo_DATA=${cfg.dataDir}"
          "zeloo_LOG=systemd"
        ];

        StateDirectory = "Zeloo";
        logsDirectory = "Zeloo";
        cacheDirectory = "Zeloo";

        Security.DisableKillUserProcesses = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        PrivateTmp = true;
        NoNewPrivileges = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
      };

      Install.WantedBy = [ "graphical-session.target" ];
    };

    environment.systemPackages = [ cfg.package ];

    networking.firewall = lib.mkIf cfg.openPorts {
      allowedTCPPorts = [ 7860 8765 9112 ];
    };

    documentation.nix.enable = lib.mkDefault false;
  };
}

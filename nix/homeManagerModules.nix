# nix/homeManagerModules.nix — the Home Manager module for Zeloo-agent
#
# This module is the user-level equivalent of nixosModules.default. Zeloo is
# an agent for one person. The credentials, the memory, the sessions and the
# cron jobs all belong to that person. Thus a user-level module is correct on
# each distribution, and not only on NixOS.
#
# `services.Zeloo-agent` is the same option set on both modules. All of the
# options except the system-level ones come from nix/moduleCommon.nix, so an
# example from the NixOS documentation works here without a change. Only the
# necessary parts are different:
#
#   removed   user, group, createUser  — Home Manager runs as the user
#   removed   container.*              — it needs root and the Docker socket
#   removed   UMask 0007               — that mode shares state with a UNIX
#                                        group, but this state has one user
#   changed   systemd.services         -> systemd.user.services or
#                                        launchd.agents
#   changed   system.activationScripts -> home.activation
#   changed   addToSystemPackages      -> programs.Zeloo-agent.enable and
#                                        home.sessionVariables
#   added     programs.Zeloo-agent    the CLI and the desktop application,
#                                      because Home Manager separates an
#                                      installation from a daemon
#   changed   stateDir (+ "/.Zeloo")  -> ZELOOHome, set directly
#
# To use the module:
#   imports = [ Zeloo-agent.homeManagerModules.default ];
#   programs.Zeloo-agent = {
#     enable = true;          # the Zeloo CLI on your PATH
#     desktop.enable = true;  # the Electron application and a launcher
#   };
#   services.Zeloo-agent = {
#     enable = true;
#     gateway.enable = true;
#     settings.model.default = "anthropic/claude-sonnet-4";
#     environmentFiles = [ config.sops.secrets."Zeloo/env".path ];
#   };
#
# CAUTION: Enable linger for the account. Without linger, systemd stops the
# user manager at logout, and both units stop with it. Home Manager cannot
# run `loginctl enable-linger`. On NixOS, set
#   users.users.<name>.linger = true;
# On other systems, run `loginctl enable-linger <name>` one time.
{ inputs, ... }:
{
  flake.homeManagerModules.default =
    {
      config,
      lib,
      options,
      pkgs,
      ...
    }:

    let
      cfg = config.services.Zeloo-agent;
      cfgPrograms = config.programs.Zeloo-agent;
      common = import ./moduleCommon.nix { inherit lib; };

      effectivePackage = common.effectivePackage cfg;
      Zeloo-agent = inputs.self.packages.${pkgs.stdenv.hostPlatform.system}.default;

      inherit (pkgs.stdenv.hostPlatform) isDarwin isLinux;

      processEnvironment = common.processEnvironment {
        inherit (cfg) ZELOOHome;
        # The CLI reads this value and names it when it refuses a
        # configuration change.
        managedSystem = "home-manager";
      };
      unitPath = lib.makeBinPath (common.processPath { inherit pkgs cfg; });

      # ── The desktop launcher ───────────────────────────────────────────
      # A GUI launcher reads no shell profile, so home.sessionVariables does
      # not reach it, and the application would open ~/.Zeloo while the
      # services use ZELOOHome. Thus the launcher carries the value itself.
      #
      # ZELOO_MANAGED rides along only when the services are enabled. That
      # variable makes the CLI refuse a configuration change and name the
      # rebuild command. A person who enables `programs.` alone has no
      # activation and no managed configuration, so the application must not
      # claim one and refuse an edit that nothing else owns.
      desktopEnvironment = {
        ZELOO_HOME = cfg.ZELOOHome;
      }
      // lib.optionalAttrs cfg.enable {
        inherit (processEnvironment) ZELOO_MANAGED;
      }
      // lib.optionalAttrs desktopUsesService {
        ZELOO_DESKTOP_REMOTE_URL = "http://${cfg.backend.host}:${toString cfg.backend.port}";
      };

      # The application reaches the backend of the service only when there is
      # a backend to reach AND a shared token to present with. Without the
      # token the desktop resolver throws ("ZELOO_DESKTOP_REMOTE_URL is set
      # but ZELOO_DESKTOP_REMOTE_TOKEN is not"), so the two variables travel
      # together or not at all.
      desktopUsesService = cfg.enable && cfg.backend.mode != "none" && cfg.backend.sessionTokenFile != null;

      # The token is read at start time and never with `--set`. makeWrapper
      # writes a --set value into the Nix store, which all users can read.
      desktopRun = lib.optional desktopUsesService ''
        if [ -r ${lib.escapeShellArg cfg.backend.sessionTokenFile} ]; then
          ZELOO_DESKTOP_REMOTE_TOKEN="$(tr -d '\r\n' < ${lib.escapeShellArg cfg.backend.sessionTokenFile})"
          export ZELOO_DESKTOP_REMOTE_TOKEN
        else
          echo "Zeloo-desktop: cannot read the session token at ${cfg.backend.sessionTokenFile}." >&2
          echo "Zeloo-desktop: the application starts its own backend instead of the one of the service." >&2
        fi
      '';

      # `override`, and not `overrideAttrs`: the values go into the wrapper
      # that the installPhase writes, and not into a derivation attribute.
      desktopPackage = cfgPrograms.desktop.package.override {
        extraEnv = desktopEnvironment;
        extraRun = desktopRun;
      };

      # The systemd unit that the gateway and the backend both start from.
      mkUnit =
        {
          description,
          argv,
        }:
        {
          Unit = {
            Description = description;
            # Do not use network-online.target here. That is a system target.
            # A user unit that orders against it has no effect, and systemd
            # gives no message.
            After = [ "default.target" ];
          };
          Install.WantedBy = [ "default.target" ];
          Service = {
            Type = "simple";
            Environment = (lib.mapAttrsToList (k: v: "${k}=${v}") processEnvironment) ++ [
              "PATH=${unitPath}"
            ];
            ExecStart = lib.escapeShellArgs argv;
            WorkingDirectory = cfg.workingDirectory;
            Restart = cfg.restart;
            RestartSec = cfg.restartSec;
            # This state has one user. Keep it private. The NixOS module uses
            # 0007 to share the state with a UNIX group.
            UMask = "0077";
            NoNewPrivileges = true;
            PrivateTmp = true;
          };
        };

      mkAgent =
        { argv, logName }:
        {
          enable = true;
          config = {
            Label = "org.nix-community.home.${logName}";
            ProgramArguments = argv;
            EnvironmentVariables = processEnvironment // {
              PATH = "${unitPath}:/usr/bin:/bin:/usr/sbin:/sbin";
            };
            WorkingDirectory = cfg.workingDirectory;
            RunAtLoad = true;
            KeepAlive =
              if cfg.restart == "always" then
                true
              else
                {
                  SuccessfulExit = false;
                  Crashed = true;
                };
            ThrottleInterval = cfg.restartSec;
            StandardOutPath = "${config.home.homeDirectory}/Library/Logs/${logName}.log";
            StandardErrorPath = "${config.home.homeDirectory}/Library/Logs/${logName}.err.log";
            ProcessType = "Background";
          };
        };

    in
    {
      # ── programs.Zeloo-agent — the installation ───────────────────────
      # Home Manager separates "install this application for me" from "run
      # this daemon". Zeloo needs both, and a person can want one without
      # the other: an application with no gateway, or a headless gateway on
      # a machine with no display.
      #
      # `services.Zeloo-agent` stays the authority for the state and the
      # configuration. This module reads ZELOOHome and the backend address
      # from it, and never the reverse.
      options.programs.Zeloo-agent = {
        enable = lib.mkEnableOption ''
          the Zeloo Agent command line application.

          This adds `Zeloo` to home.packages, and exports ZELOO_HOME with
          home.sessionVariables. An interactive shell then uses the same
          state as `services.Zeloo-agent`
        '';

        package = lib.mkOption {
          type = lib.types.package;
          default = effectivePackage;
          defaultText = lib.literalExpression "config.services.Zeloo-agent.package";
          description = ''
            The Zeloo-agent package to install.

            The default follows `services.Zeloo-agent.package`, and applies
            `extraPythonPackages` and `extraDependencyGroups` from that
            module. Thus the command line and the services are one build,
            and a plugin that the services can load is a plugin that your
            shell can load.
          '';
        };

        desktop = {
          enable = lib.mkEnableOption ''
            the Zeloo Desktop application (Electron).

            This adds `Zeloo-desktop` to home.packages, with an XDG
            launcher entry on Linux. The launcher starts the same Zeloo
            runtime that `package` gives, and reads the ZELOO_HOME of
            `services.Zeloo-agent`. Thus the application, the interactive
            shell and the services share one state directory.

            The Electron application carries its own Zeloo runtime with
            the usual distribution. This module gives it the Nix package
            instead, with ZELOO_DESKTOP_ZELOO. It installs no second copy
            of Zeloo, and it downloads nothing on the first start
          '';

          package = lib.mkOption {
            type = lib.types.package;
            default = cfgPrograms.package.ZELOODesktop;
            defaultText = lib.literalExpression "config.programs.Zeloo-agent.package.ZELOODesktop";
            description = ''
              The Zeloo-desktop package to use.

              The default follows `package`, and thus also
              `services.Zeloo-agent.extraPythonPackages` and
              `extraDependencyGroups`, because the desktop application is a
              passthru of the agent package. A package that you set here
              carries its own Zeloo runtime, and this module cannot make
              it agree with the services.
            '';
          };
        };
      };

      options.services.Zeloo-agent =
        common.sharedOptions {
          defaultPackage = Zeloo-agent;
          defaultPackageText = lib.literalExpression "Zeloo-agent.packages.\${system}.default";
          defaultWorkingDirectory = config.home.homeDirectory;
          defaultWorkingDirectoryText = lib.literalExpression "config.home.homeDirectory";
        }
        // {
          ZELOOHome = lib.mkOption {
            type = lib.types.str;
            default = "${config.home.homeDirectory}/.Zeloo";
            defaultText = lib.literalExpression ''"''${config.home.homeDirectory}/.Zeloo"'';
            description = ''
              The value of ZELOO_HOME. This state directory holds
              config.yaml, .env, auth.json, the sessions, the skills, the
              memory and the cron jobs.

              The NixOS module takes a `stateDir` and adds `/.Zeloo` to it.
              This module sets ZELOO_HOME directly. Thus an existing
              ~/.Zeloo continues to work, and you can give the directory any
              name.
            '';
            example = "/home/alice/.Zeloo-work";
          };

          # `installPackage` moved to `programs.Zeloo-agent.enable`. The
          # option is dead, but it must not be silent: it defaulted to true,
          # so a person who never named it still got the command line, and a
          # quiet removal gives them a machine with no `Zeloo` and no
          # message. mkOption with an assertion, and not
          # mkRemovedOptionModule, because the message must name the exact
          # replacement for the value they set.
          installPackage = lib.mkOption {
            type = lib.types.nullOr lib.types.bool;
            default = null;
            visible = false;
            description = ''
              Removed. Use `programs.Zeloo-agent.enable` instead.
            '';
          };

          gateway.enable = lib.mkEnableOption "the messaging gateway service (Telegram, Discord, Slack, ...)";
        };

      config = lib.mkMerge [

        # ── programs.Zeloo-agent — the installation ──────────────────────
        # Outside the `services.enable` guard on purpose. A person can want
        # the command line or the application on a machine that runs no
        # daemon at all.
        (lib.mkIf cfgPrograms.enable {
          home.packages = [ cfgPrograms.package ];
          home.sessionVariables.ZELOO_HOME = cfg.ZELOOHome;
        })

        # A launcher from the desktop menu reads no shell profile, so the
        # ZELOO_HOME that `programs.enable` exports does not reach it. Home
        # Manager writes only systemd.user.sessionVariables into
        # environment.d, and this module does not put ZELOO_HOME there,
        # because that file applies to each user unit. Thus the launcher
        # carries the value itself. See desktopEnvironment above.
        (lib.mkIf cfgPrograms.desktop.enable {
          home.packages = [ desktopPackage ];
        })

        {
          assertions = [
            {
              # `installPackage` was removed in favour of the programs/services
              # split. It defaulted to true, so a quiet removal leaves a person
              # with no `Zeloo` on the PATH and no message.
              assertion = cfg.installPackage == null;
              message = common.installPackageRemovedMessage cfg.installPackage;
            }
          ];
        }

        (lib.mkIf cfg.enable (
          lib.mkMerge [

            # ── Merge MCP servers into settings ────────────────────────────
            (lib.mkIf (cfg.mcpServers != { }) {
              services.Zeloo-agent.settings.mcp_servers = common.mcpServersToConfig cfg.mcpServers;
            })

            {
              assertions =
                common.pluginNameAssertions {
                  inherit cfg;
                  optionPath = "services.Zeloo-agent";
                }
                ++ common.workspaceFilesAssertions {
                  inherit cfg;
                  opt = options.services.Zeloo-agent.workingDirectory;
                  optionPath = "services.Zeloo-agent";
                }
                ++ common.backendBindAssertions {
                  inherit cfg;
                  optionPath = "services.Zeloo-agent";
                }
                ++ [
                  {
                    # The interface poll reads `ip`, which iproute2 supplies on
                    # Linux only.
                    assertion = !isDarwin || cfg.backend.waitFor != "interface";
                    message = "services.Zeloo-agent.backend.waitFor = \"interface\" works on Linux only. Use \"hostname\" on Darwin.";
                  }
                ];
            }

            # The agent runs these tools, so they belong on the PATH of the
            # person as well as in the unit.
            (lib.mkIf cfgPrograms.enable {
              home.packages = cfg.extraPackages;
            })

            # ── Activation: directories, config, secrets, documents ────────
            {
              # The activation runs after writeBoundary, when the home.file
              # symlinks are in place. It also runs after linkGeneration, when
              # Home Manager completes the switch. A secret that the activation
              # entry of sops-nix writes exists at that point.
              home.activation.ZELOOAgentSetup =
                lib.hm.dag.entryAfter
                  [
                    "writeBoundary"
                    "linkGeneration"
                  ]
                  (
                    common.mkStateScript {
                      inherit pkgs cfg;
                      inherit (cfg) ZELOOHome workingDirectory;
                      run = "$DRY_RUN_CMD ";
                      stateDirs = common.stateSubdirs;
                      managedSystem = "home-manager";
                      # This state has one user. No group needs access to it.
                      modes = {
                        config = "0600";
                        env = "0600";
                        managed = "0600";
                        auth = "0600";
                        document = "0600";
                      };
                    }
                  );
            }

            # ── Linux: systemd user services ───────────────────────────────
            (lib.mkIf (isLinux && cfg.gateway.enable) {
              systemd.user.services.Zeloo-agent = mkUnit {
                description = "Zeloo Agent Gateway";
                argv = common.gatewayArgv cfg;
              };
            })

            (lib.mkIf (isLinux && cfg.backend.mode != "none") {
              systemd.user.services.Zeloo-backend = mkUnit {
                description = common.backendDescription cfg;
                argv = common.backendArgv { inherit pkgs cfg; };
              };
            })

            # ── Darwin: launchd agents ─────────────────────────────────────
            (lib.mkIf (isDarwin && cfg.gateway.enable) {
              launchd.agents.Zeloo-agent = mkAgent {
                argv = common.gatewayArgv cfg;
                logName = "Zeloo-agent";
              };
            })

            (lib.mkIf (isDarwin && cfg.backend.mode != "none") {
              launchd.agents.Zeloo-backend = mkAgent {
                argv = common.backendArgv { inherit pkgs cfg; };
                logName = "Zeloo-backend";
              };
            })
          ]
        ))
      ];
    };
}

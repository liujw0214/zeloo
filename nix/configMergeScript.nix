{ config, lib, pkgs, ... }:

let
  cfg = config.services.Zeloo;

  workspaceArgs = lib.concatMapStringsSep " " (ws: "--workspace ${ws}") cfg.workspaceDefaults;
in
{
  imports = [
    ./homeManagerModules.nix
  ];

  options.services.Zeloo = lib.mkOption {
    description = "Zeloo Agent Runtime NixOS configuration";
  } // lib.mkOption {
    type = lib.types.submodule {
      options = {
        enable = lib.mkEnableOption "Enable Zeloo Agent Runtime";

        package = lib.mkOption {
          type = lib.types.package;
          default = pkgs.Zeloo or (pkgs.callPackage ./Zeloo.nix { });
          description = "Zeloo package to use";
        };

        systemWide = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = "Install system-wide for all users";
        };

        user = lib.mkOption {
          type = lib.types.str;
          default = "Zeloo";
          description = "User account to run Zeloo as";
        };

        group = lib.mkOption {
          type = lib.types.str;
          default = "Zeloo";
          description = "Group account to run Zeloo as";
        };

        dataDir = lib.mkOption {
          type = lib.types.path;
          default = "/var/lib/Zeloo";
          description = "Data directory for Zeloo runtime state";
        };

        workspaceDefaults = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ "default" ];
          description = "Pre-created workspace names";
        };

        openPorts = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = "Open firewall ports for Zeloo API (7860, 8765, 9112)";
        };

        # ───────── Backup ─────────
        backup.enable = lib.mkEnableOption "Automated backup of Zeloo data";
        backup.interval = lib.mkOption {
          type = lib.types.str;
          default = "daily";
          description = "Backup frequency (daily, weekly, hourly)";
        };
        backup.retention = lib.mkOption {
          type = lib.types.int;
          default = 7;
          description = "Number of backups to retain";
        };
        backup.destDir = lib.mkOption {
          type = lib.types.path;
          default = "/var/backups/Zeloo";
          description = "Destination directory for backup archives";
        };

        # ───────── Monitoring ─────────
        monitoring.prometheus.enable = lib.mkEnableOption "Prometheus metrics endpoint";
        monitoring.prometheus.port = lib.mkOption {
          type = lib.types.port;
          default = 9112;
          description = "Port for Prometheus metrics";
        };
        monitoring.logLevel = lib.mkOption {
          type = lib.types.enum [ "debug" "info" "warn" "error" ];
          default = "info";
          description = "Logging verbosity";
        };

        # ───────── Reverse Proxy ─────────
        reverseProxy = {
          enable = lib.mkEnableOption "Enable nginx reverse proxy";
          domain = lib.mkOption {
            type = lib.types.str;
            default = "Zeloo.local";
            description = "Public domain name";
          };
          port = lib.mkOption {
            type = lib.types.port;
            default = 443;
            description = "Public HTTPS port";
          };
          ssl = lib.mkOption {
            type = lib.types.enum [ "selfsigned" "letsencrypt" "none" ];
            default = "selfsigned";
            description = "SSL/TLS certificate source";
          };
          websockets = lib.mkEnableOption "Proxy WebSocket connections";
        };

        # ───────── High Availability ─────────
        ha = {
          enable = lib.mkEnableOption "High availability mode (systemd watchdog)";
          watchdogSec = lib.mkOption {
            type = lib.types.int;
            default = 30;
            description = "Watchdog timeout in seconds";
          };
          restartMaxAttempts = lib.mkOption {
            type = lib.types.int;
            default = 5;
            description = "Max restart attempts within StartLimitIntervalSec";
          };
          startLimitIntervalSec = lib.mkOption {
            type = lib.types.int;
            default = 300;
            description = "Restart limit window in seconds";
          };
        };

        # ───────── Time Sync ─────────
        timeSync = {
          enable = lib.mkEnableOption "Enable NTP time synchronization";
          servers = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ "pool.ntp.org" "time.nist.gov" ];
            description = "NTP servers to use";
          };
        };

        # ───────── Resources ─────────
        resources = {
          memoryMax = lib.mkOption {
            type = lib.types.str;
            default = "2G";
            description = "Memory max limit (e.g., 2G, 512M)";
          };
          cpuQuota = lib.mkOption {
            type = lib.types.str;
            default = "200%";
            description = "CPU quota percentage";
          };
        };

        # ───────── Secrets ─────────
        secrets = {
          apiKeysFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to API keys file (must be readable by Zeloo user)";
          };
          envFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to environment file";
          };
          sopsFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to SOPS-encrypted secrets YAML";
          };
          ageKeyFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to age key for SOPS decryption";
          };
        };

        # ───────── Multi-instance support ─────────
        instances = lib.mkOption {
          type = lib.types.attrsOf lib.types.submodule {
            options = {
              enable = lib.mkEnableOption "Enable this instance";
              dataDir = lib.mkOption {
                type = lib.types.path;
                description = "Instance-specific data directory";
              };
              port = lib.mkOption {
                type = lib.types.port;
                description = "Instance API port";
              };
              workspaces = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                description = "Workspaces for this instance";
              };
              model = lib.mkOption {
                type = lib.types.str;
                default = "default";
                description = "Default model for this instance";
              };
            };
          };
          default = { };
          description = "Multiple Zeloo instances on the same host";
        };

        # ───────── Cluster / distributed mode ─────────
        cluster = {
          enable = lib.mkEnableOption "Enable cluster mode (Redis coordination)";
          redisHost = lib.mkOption {
            type = lib.types.str;
            default = "127.0.0.1";
            description = "Redis server for cluster coordination";
          };
          redisPort = lib.mkOption {
            type = lib.types.port;
            default = 6379;
            description = "Redis port";
          };
          nodeId = lib.mkOption {
            type = lib.types.str;
            default = "node-1";
            description = "Unique node identifier in cluster";
          };
          sharedStorage = lib.mkOption {
            type = lib.types.path;
            default = "/var/lib/Zeloo-shared";
            description = "Shared storage path (NFS/GlusterFS)";
          };
        };

        # ───────── Container runtime (Podman) ─────────
        container = {
          enable = lib.mkEnableOption "Run Zeloo as a rootless Podman container";
          image = lib.mkOption {
            type = lib.types.str;
            default = "ghcr.io/your-org/Zeloo:latest";
            description = "Container image to run";
          };
          imageTag = lib.mkOption {
            type = lib.types.str;
            default = "stable";
            description = "Image tag for auto-updates";
          };
          autoUpdate = lib.mkEnableOption "Enable automatic image updates";
          network = lib.mkOption {
            type = lib.types.str;
            default = "host";
            description = "Container network mode (host/bridge/none)";
          };
          userNamespace = lib.mkEnableOption "Enable user namespace mapping";
        };

        # ───────── OpenTelemetry tracing ─────────
        tracing = {
          enable = lib.mkEnableOption "Enable OpenTelemetry distributed tracing";
          endpoint = lib.mkOption {
            type = lib.types.str;
            default = "http://localhost:4317";
            description = "OTLP gRPC endpoint";
          };
          serviceName = lib.mkOption {
            type = lib.types.str;
            default = "Zeloo";
            description = "Service name for traces";
          };
          sampleRate = lib.mkOption {
            type = lib.types.float;
            default = 0.1;
            description = "Trace sampling rate (0.0-1.0)";
          };
        };

        # ───────── Database backend selection ─────────
        database = {
          backend = lib.mkOption {
            type = lib.types.enum [ "sqlite" "postgres" ];
            default = "sqlite";
            description = "Database backend for session storage";
          };
          postgres = {
            host = lib.mkOption {
              type = lib.types.str;
              default = "127.0.0.1";
              description = "PostgreSQL host";
            };
            port = lib.mkOption {
              type = lib.types.port;
              default = 5432;
              description = "PostgreSQL port";
            };
            database = lib.mkOption {
              type = lib.types.str;
              default = "Zeloo";
              description = "PostgreSQL database name";
            };
            user = lib.mkOption {
              type = lib.types.str;
              default = "Zeloo";
              description = "PostgreSQL user";
            };
          };
        };

        # ───────── Rate limiting ─────────
        rateLimit = {
          enable = lib.mkEnableOption "Enable API rate limiting";
          requestsPerMinute = lib.mkOption {
            type = lib.types.int;
            default = 60;
            description = "Max requests per minute per client";
          };
          burst = lib.mkOption {
            type = lib.types.int;
            default = 100;
            description = "Burst capacity";
          };
        };

        # ───────── TLS termination ─────────
        tls = {
          enable = lib.mkEnableOption "Enable TLS termination";
          certFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to TLS certificate (PEM)";
          };
          keyFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to TLS private key (PEM)";
          };
          minVersion = lib.mkOption {
            type = lib.types.enum [ "1.2" "1.3" ];
            default = "1.2";
            description = "Minimum TLS version";
          };
          hsts = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Enable HTTP Strict Transport Security";
          };
          clientCertAuth = lib.mkEnableOption "Require client certificate authentication (mTLS)";
        };

        # ───────── Canary / blue-green deployment ─────────
        canary = {
          enable = lib.mkEnableOption "Enable canary deployment slot";
          weight = lib.mkOption {
            type = lib.types.ints.between 0 100;
            default = 10;
            description = "Percentage of traffic routed to canary (0-100)";
          };
          autoPromote = lib.mkOption {
            type = lib.types.bool;
            default = false;
            description = "Auto-promote canary to production on health check pass";
          };
          healthCheckInterval = lib.mkOption {
            type = lib.types.int;
            default = 30;
            description = "Canary health check interval in seconds";
          };
        };

        # ───────── A/B testing ─────────
        abTest = {
          enable = lib.mkEnableOption "Enable A/B testing framework";
          experiments = lib.mkOption {
            type = lib.types.attrsOf lib.types.submodule {
              options = {
                weight = lib.mkOption {
                  type = lib.types.ints.between 0 100;
                  default = 50;
                  description = "Traffic percentage for this variant";
                };
                model = lib.mkOption {
                  type = lib.types.str;
                  description = "Model to use for this variant";
                };
                metadata = lib.mkOption {
                  type = lib.types.attrsOf lib.types.str;
                  default = { };
                  description = "Variant metadata";
                };
              };
            };
            default = { };
            description = "A/B test experiments";
          };
        };

        # ───────── Kubernetes Operator ─────────
        kubernetes = {
          enable = lib.mkEnableOption "Deploy Zeloo Kubernetes operator";
          namespace = lib.mkOption {
            type = lib.types.str;
            default = "Zeloo-system";
            description = "Kubernetes namespace for operator";
          };
          replicas = lib.mkOption {
            type = lib.types.int;
            default = 1;
            description = "Number of operator replicas";
          };
          chart = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to Helm chart";
          };
        };

        # ───────── Backup encryption ─────────
        backupEncryption = {
          enable = lib.mkEnableOption "Encrypt backup archives";
          publicKeyFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to age public key for backup encryption";
          };
        };

        # ───────── Cost controls ─────────
        costControl = {
          enable = lib.mkEnableOption "Enable cost control limits";
          monthlyBudgetUSD = lib.mkOption {
            type = lib.types.float;
            default = 100.0;
            description = "Monthly budget cap in USD";
          };
          alertThreshold = lib.mkOption {
            type = lib.types.float;
            default = 0.8;
            description = "Alert when usage reaches this fraction of budget (0.0-1.0)";
          };
          enforceHardLimit = lib.mkOption {
            type = lib.types.bool;
            default = false;
            description = "Hard-stop when budget exceeded (vs alert-only)";
          };
        };

        # ───────── Authentication integration ─────────
        auth = {
          method = lib.mkOption {
            type = lib.types.enum [ "none" "basic" "oauth2" "oidc" "ldap" ];
            default = "none";
            description = "Authentication method for API";
          };
          oidcIssuer = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "OIDC issuer URL";
          };
          oidcClientId = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "OIDC client ID";
          };
          ldapHost = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "LDAP server host";
          };
          ldapBaseDn = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "LDAP base DN";
          };
        };

        # ───────── Compliance / audit ─────────
        audit = {
          enable = lib.mkEnableOption "Enable audit logging";
          logFile = lib.mkOption {
            type = lib.types.path;
            default = "/var/log/Zeloo/audit.log";
            description = "Audit log file path";
          };
          retentionDays = lib.mkOption {
            type = lib.types.int;
            default = 90;
            description = "Audit log retention in days";
          };
          includeRequestBody = lib.mkOption {
            type = lib.types.bool;
            default = false;
            description = "Include request bodies in audit logs (may contain PII)";
          };
        };

        # ───────── Disaster Recovery (DR) ─────────
        disasterRecovery = {
          enable = lib.mkEnableOption "Enable disaster recovery replication";
          primaryHost = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Primary site hostname (for replica sync)";
          };
          replicaHost = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Replica site hostname";
          };
          syncIntervalSec = lib.mkOption {
            type = lib.types.int;
            default = 300;
            description = "Replication sync interval in seconds";
          };
          rpoSec = lib.mkOption {
            type = lib.types.int;
            default = 60;
            description = "Recovery Point Objective in seconds";
          };
          rtoSec = lib.mkOption {
            type = lib.types.int;
            default = 600;
            description = "Recovery Time Objective in seconds";
          };
          autoFailover = lib.mkEnableOption "Automatic failover when primary is unreachable";
        };

        # ───────── GitOps / config-as-code ─────────
        gitOps = {
          enable = lib.mkEnableOption "Enable GitOps-style config sync";
          repoUrl = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Git repository URL containing Zeloo config";
          };
          branch = lib.mkOption {
            type = lib.types.str;
            default = "main";
            description = "Git branch to track";
          };
          pollIntervalSec = lib.mkOption {
            type = lib.types.int;
            default = 60;
            description = "How often to poll the repository for changes";
          };
          sshKeyFile = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "SSH private key for Git authentication";
          };
        };

        # ───────── Service Mesh (Linkerd/Istio) ─────────
        serviceMesh = {
          enable = lib.mkEnableOption "Enable service mesh integration";
          type = lib.mkOption {
            type = lib.types.enum [ "linkerd" "istio" "consul" ];
            default = "linkerd";
            description = "Service mesh type";
          };
          injectSidecar = lib.mkEnableOption "Inject sidecar proxy into Zeloo";
          mtls = lib.mkEnableOption "Enable strict mutual TLS between mesh services";
        };

        # ───────── Multi-region / geo-replication ─────────
        geoReplication = {
          enable = lib.mkEnableOption "Enable multi-region replication";
          regions = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
            example = [ "us-west" "us-east" "eu-central" ];
            description = "Active regions";
          };
          currentRegion = lib.mkOption {
            type = lib.types.str;
            default = "us-west";
            description = "This node's region";
          };
          replicationStrategy = lib.mkOption {
            type = lib.types.enum [ "sync" "async" "leader-follower" ];
            default = "async";
            description = "Replication strategy across regions";
          };
        };

        # ───────── Webhooks / event bus ─────────
        webhooks = {
          enable = lib.mkEnableOption "Enable webhook event publishing";
          endpoints = lib.mkOption {
            type = lib.types.listOf lib.types.submodule {
              options = {
                url = lib.mkOption {
                  type = lib.types.str;
                  description = "Webhook target URL";
                };
                events = lib.mkOption {
                  type = lib.types.listOf lib.types.str;
                  example = [ "session.start" "session.end" "tool.error" ];
                  description = "Event types to subscribe to";
                };
                secret = lib.mkOption {
                  type = lib.types.nullOr lib.types.str;
                  default = null;
                  description = "HMAC secret for webhook signature";
                };
                timeout = lib.mkOption {
                  type = lib.types.int;
                  default = 10;
                  description = "Request timeout in seconds";
                };
              };
            };
            default = [ ];
            description = "Webhook endpoints";
          };
        };

        # ───────── Plugin sandboxing ─────────
        pluginSecurity = {
          sandbox = lib.mkEnableOption "Enable plugin sandboxing (gVisor/Firecracker)";
          networkAccess = lib.mkOption {
            type = lib.types.enum [ "none" "restricted" "full" ];
            default = "restricted";
            description = "Plugin network access level";
          };
          fileSystemAccess = lib.mkOption {
            type = lib.types.enum [ "readonly" "workspace-only" "full" ];
            default = "workspace-only";
            description = "Plugin filesystem access level";
          };
          cpuLimit = lib.mkOption {
            type = lib.types.str;
            default = "100%";
            description = "Plugin CPU quota";
          };
          memoryLimit = lib.mkOption {
            type = lib.types.str;
            default = "512M";
            description = "Plugin memory limit";
          };
        };

        # ───────── Notification channels ─────────
        notifications = {
          slack = {
            enable = lib.mkEnableOption "Enable Slack notifications";
            webhookUrl = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Slack incoming webhook URL";
            };
          };
          email = {
            enable = lib.mkEnableOption "Enable email notifications";
            smtpHost = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "SMTP server host";
            };
            from = lib.mkOption {
              type = lib.types.str;
              default = "Zeloo@localhost";
              description = "From address";
            };
            to = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              description = "Recipient addresses";
            };
          };
          pagerduty = {
            enable = lib.mkEnableOption "Enable PagerDuty integration";
            integrationKey = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "PagerDuty Events API integration key";
            };
          };
        };

        # ───────── Quota management ─────────
        quota = {
          maxSessionsPerUser = lib.mkOption {
            type = lib.types.int;
            default = 100;
            description = "Max concurrent sessions per user";
          };
          maxTokensPerDay = lib.mkOption {
            type = lib.types.nullOr lib.types.int;
            default = null;
            description = "Max tokens per day across all sessions";
          };
          maxStorageGB = lib.mkOption {
            type = lib.types.int;
            default = 10;
            description = "Max storage per workspace in GB";
          };
        };

        # ───────── Custom themes / branding ─────────
        branding = {
          name = lib.mkOption {
            type = lib.types.str;
            default = "Zeloo";
            description = "Display name in UI";
          };
          logoUrl = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Logo URL (must be HTTPS)";
          };
          primaryColor = lib.mkOption {
            type = lib.types.str;
            default = "#0066cc";
            description = "Primary brand color (hex)";
          };
          customCss = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Custom CSS file for branding";
          };
        };

        # ───────── Feature flags ─────────
        featureFlags = {
          enable = lib.mkEnableOption "Enable feature flag system";
          flags = lib.mkOption {
            type = lib.types.attrsOf lib.types.submodule {
              options = {
                enabled = lib.mkOption {
                  type = lib.types.bool;
                  default = false;
                  description = "Whether this feature is enabled";
                };
                rollout = lib.mkOption {
                  type = lib.types.ints.between 0 100;
                  default = 100;
                  description = "Percentage rollout (0-100)";
                };
                usersAllowlist = lib.mkOption {
                  type = lib.types.listOf lib.types.str;
                  default = [ ];
                  description = "User IDs always allowed";
                };
                usersBlocklist = lib.mkOption {
                  type = lib.types.listOf lib.types.str;
                  default = [ ];
                  description = "User IDs always blocked";
                };
              };
            };
            default = { };
            description = "Feature flag definitions";
          };
        };

        # ───────── SLO (Service Level Objectives) ─────────
        slo = {
          enable = lib.mkEnableOption "Enable SLO monitoring";
          availability = lib.mkOption {
            type = lib.types.float;
            default = 0.999;
            description = "Availability target (0.0-1.0)";
          };
          latencyP99Ms = lib.mkOption {
            type = lib.types.int;
            default = 500;
            description = "P99 latency target in milliseconds";
          };
          errorBudget = lib.mkOption {
            type = lib.types.float;
            default = 0.001;
            description = "Error budget as fraction of total requests";
          };
          windowDays = lib.mkOption {
            type = lib.types.int;
            default = 30;
            description = "SLO measurement window in days";
          };
        };

        # ───────── Chaos engineering ─────────
        chaos = {
          enable = lib.mkEnableOption "Enable chaos engineering experiments";
          latencyInjectionMs = lib.mkOption {
            type = lib.types.int;
            default = 0;
            description = "Inject artificial latency (ms) for testing";
          };
          errorRate = lib.mkOption {
            type = lib.types.float;
            default = 0.0;
            description = "Inject errors at this rate (0.0-1.0)";
          };
          killSwitch = lib.mkOption {
            type = lib.types.path;
            default = "/var/lib/Zeloo/.chaos-enabled";
            description = "Touch this file to disable chaos experiments";
          };
          scheduleCron = lib.mkOption {
            type = lib.types.str;
            default = "";
            description = "Cron schedule for chaos experiments";
          };
        };

        # ───────── CI/CD integration ─────────
        ci = {
          provider = lib.mkOption {
            type = lib.types.enum [ "github" "gitlab" "circleci" "jenkins" ];
            default = "github";
            description = "CI/CD provider";
          };
          webhookUrl = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "CI/CD webhook URL for status updates";
          };
          autoDeploy = lib.mkEnableOption "Auto-deploy on successful CI build";
          deployBranch = lib.mkOption {
            type = lib.types.str;
            default = "main";
            description = "Branch to auto-deploy from";
          };
        };

        # ───────── Compliance frameworks ─────────
        compliance = {
          framework = lib.mkOption {
            type = lib.types.enum [ "none" "soc2" "hipaa" "gdpr" "iso27001" ];
            default = "none";
            description = "Compliance framework to enforce";
          };
          dataRetentionDays = lib.mkOption {
            type = lib.types.int;
            default = 365;
            description = "Data retention period in days";
          };
          rightToBeForgotten = lib.mkEnableOption "Enable GDPR right-to-be-forgotten endpoints";
          dataResidencyRegion = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Required data residency region (e.g., EU, US)";
          };
          piiRedaction = lib.mkEnableOption "Redact PII from logs and traces";
        };

        # ───────── Performance budgets ─────────
        perfBudget = {
          coldStartSec = lib.mkOption {
            type = lib.types.float;
            default = 2.0;
            description = "Maximum cold start time in seconds";
          };
          memoryCeilingMb = lib.mkOption {
            type = lib.types.int;
            default = 512;
            description = "Memory ceiling per session in MB";
          };
          tokenThroughputPerMin = lib.mkOption {
            type = lib.types.int;
            default = 10000;
            description = "Minimum token throughput per minute";
          };
        };

        # ───────── Streaming output ─────────
        streaming = {
          bufferSizeKb = lib.mkOption {
            type = lib.types.int;
            default = 64;
            description = "Streaming buffer size in KB";
          };
          flushIntervalMs = lib.mkOption {
            type = lib.types.int;
            default = 100;
            description = "How often to flush streamed output (ms)";
          };
          compression = lib.mkOption {
            type = lib.types.enum [ "none" "gzip" "zstd" "brotli" ];
            default = "zstd";
            description = "Compression algorithm for streamed output";
          };
        };

        # ───────── Observability exporters ─────────
        observabilityExporters = {
          otlp = {
            enable = lib.mkEnableOption "OTLP exporter";
            endpoint = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "OTLP endpoint URL";
            };
          };
          prometheus = {
            enable = lib.mkEnableOption "Prometheus exporter";
            port = lib.mkOption {
              type = lib.types.port;
              default = 9090;
              description = "Prometheus exporter port";
            };
          };
          jaeger = {
            enable = lib.mkEnableOption "Jaeger exporter";
            endpoint = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Jaeger collector endpoint";
            };
          };
          loki = {
            enable = lib.mkEnableOption "Loki log exporter";
            endpoint = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Loki push endpoint";
            };
          };
        };

        # ───────── AI safety controls ─────────
        aiSafety = {
          enable = lib.mkEnableOption "Enable AI safety controls";
          contentFilter = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Filter harmful content";
          };
          promptInjectionDetection = lib.mkEnableOption "Detect prompt injection attempts";
          jailbreakDetection = lib.mkEnableOption "Detect jailbreak attempts";
          outputSanitization = lib.mkEnableOption "Sanitize output for credentials";
          maxContextLength = lib.mkOption {
            type = lib.types.int;
            default = 200000;
            description = "Maximum context length in tokens";
          };
        };

        # ───────── Event sourcing ─────────
        eventSourcing = {
          enable = lib.mkEnableOption "Enable event sourcing for sessions";
          store = lib.mkOption {
            type = lib.types.enum [ "sqlite" "postgres" "kafka" ];
            default = "sqlite";
            description = "Event store backend";
          };
          snapshotInterval = lib.mkOption {
            type = lib.types.int;
            default = 100;
            description = "Snapshot every N events";
          };
          retentionDays = lib.mkOption {
            type = lib.types.int;
            default = 90;
            description = "Event retention in days";
          };
        };

        # ───────── CQRS read model cache ─────────
        cqrs = {
          enable = lib.mkEnableOption "Enable CQRS read/write split";
          readReplicas = lib.mkOption {
            type = lib.types.int;
            default = 1;
            description = "Number of read replicas";
          };
          cacheBackend = lib.mkOption {
            type = lib.types.enum [ "memory" "redis" "memcached" ];
            default = "memory";
            description = "Read-side cache backend";
          };
          cacheTtlSec = lib.mkOption {
            type = lib.types.int;
            default = 300;
            description = "Cache TTL in seconds";
          };
        };

        # ───────── Model governance ─────────
        modelGovernance = {
          allowlist = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
            example = [ "gpt-4o" "claude-3-5-sonnet-latest" ];
            description = "Models allowed for use (empty = all)";
          };
          blocklist = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
            description = "Models blocked from use";
          };
          requireApproval = lib.mkEnableOption "Require approval for new models";
          costCeilingPerCall = lib.mkOption {
            type = lib.types.nullOr lib.types.float;
            default = null;
            description = "Max USD per single API call";
          };
          latencyCeilingMs = lib.mkOption {
            type = lib.types.nullOr lib.types.int;
            default = null;
            description = "Max latency per call (ms)";
          };
        };

        # ───────── Workspace templates ─────────
        workspaceTemplates = {
          enable = lib.mkEnableOption "Enable workspace templates";
          registry = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Path to template registry YAML";
          };
          autoSync = lib.mkEnableOption "Auto-sync templates from Git";
          defaultTemplates = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ "default" "research" "minimal" ];
            description = "Default workspace templates to provision";
          };
        };

        # ───────── Federated learning / model distillation ─────────
        federatedLearning = {
          enable = lib.mkEnableOption "Enable federated learning across instances";
          coordinator = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Federation coordinator URL";
          };
          privacyLevel = lib.mkOption {
            type = lib.types.enum [ "none" "differential" "homomorphic" ];
            default = "differential";
            description = "Privacy-preserving technique";
          };
          noiseEpsilon = lib.mkOption {
            type = lib.types.float;
            default = 1.0;
            description = "Differential privacy epsilon";
          };
        };

        # ───────── Cache policies ─────────
        cachePolicy = {
          promptCache = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Cache prompt prefixes for reuse";
          };
          responseCache = lib.mkOption {
            type = lib.types.bool;
            default = false;
            description = "Cache full responses";
          };
          maxCacheSizeMb = lib.mkOption {
            type = lib.types.int;
            default = 256;
            description = "Max prompt cache size (MB)";
          };
          ttlSec = lib.mkOption {
            type = lib.types.int;
            default = 3600;
            description = "Cache TTL in seconds";
          };
        };

        # ───────── I18n / l10n ─────────
        i18n = {
          defaultLocale = lib.mkOption {
            type = lib.types.str;
            default = "en";
            description = "Default locale";
          };
          supportedLocales = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ "en" ];
            example = [ "en" "zh-CN" "es" ];
            description = "List of supported locales";
          };
          dateFormat = lib.mkOption {
            type = lib.types.enum [ "ISO8601" "RFC2822" "locale" ];
            default = "ISO8601";
            description = "Date format";
          };
          timezone = lib.mkOption {
            type = lib.types.str;
            default = "UTC";
            description = "Default timezone (IANA)";
          };
        };

        # ───────── Custom model adapters ─────────
        modelAdapters = {
          enable = lib.mkEnableOption "Enable custom model adapters";
          directory = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Directory containing custom adapter .py files";
          };
          hotReload = lib.mkEnableOption "Hot-reload adapters on file change";
        };

        # ───────── Test framework ─────────
        testing = {
          enableTestMode = lib.mkEnableOption "Enable test mode (uses fake providers)";
          coverageThreshold = lib.mkOption {
            type = lib.types.float;
            default = 0.8;
            description = "Minimum code coverage threshold (0.0-1.0)";
          };
          parallelJobs = lib.mkOption {
            type = lib.types.int;
            default = 4;
            description = "Parallel test execution jobs";
          };
        };

        # ───────── Database migrations ─────────
        dbMigrations = {
          autoMigrate = lib.mkEnableOption "Automatically run DB migrations on startup";
          backupBeforeMigrate = lib.mkEnableOption "Backup database before migrations";
          timeoutSec = lib.mkOption {
            type = lib.types.int;
            default = 300;
            description = "Migration timeout in seconds";
          };
          lockTimeoutSec = lib.mkOption {
            type = lib.types.int;
            default = 60;
            description = "Database lock timeout for migrations";
          };
        };

        # ───────── Token bucket rate limiter ─────────
        tokenBucket = {
          enable = lib.mkEnableOption "Enable token-bucket rate limiting";
          capacity = lib.mkOption {
            type = lib.types.int;
            default = 100;
            description = "Bucket capacity";
          };
          refillRatePerSec = lib.mkOption {
            type = lib.types.float;
            default = 10.0;
            description = "Token refill rate per second";
          };
          burstMultiplier = lib.mkOption {
            type = lib.types.float;
            default = 1.5;
            description = "Burst multiplier (capacity × multiplier = max burst)";
          };
        };

        # ───────── Circuit breaker ─────────
        circuitBreaker = {
          enable = lib.mkEnableOption "Enable circuit breaker pattern";
          failureThreshold = lib.mkOption {
            type = lib.types.int;
            default = 5;
            description = "Consecutive failures to open circuit";
          };
          resetTimeoutSec = lib.mkOption {
            type = lib.types.int;
            default = 30;
            description = "Time before attempting reset";
          };
          halfOpenRequests = lib.mkOption {
            type = lib.types.int;
            default = 1;
            description = "Probe requests in half-open state";
          };
        };

        # ───────── Progressive rollout ─────────
        rollout = {
          strategy = lib.mkOption {
            type = lib.types.enum [ "all-at-once" "rolling" "blue-green" "canary" ];
            default = "rolling";
            description = "Deployment strategy";
          };
          batchSize = lib.mkOption {
            type = lib.types.int;
            default = 1;
            description = "Instances per batch";
          };
          batchDelaySec = lib.mkOption {
            type = lib.types.int;
            default = 30;
            description = "Delay between batches";
          };
          healthCheckTimeout = lib.mkOption {
            type = lib.types.int;
            default = 300;
            description = "Health check timeout per batch (sec)";
          };
          abortOnFailure = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Abort rollout on any batch failure";
          };
        };

        # ───────── Resource quotas / fair scheduling ─────────
        scheduling = {
          maxConcurrentSessions = lib.mkOption {
            type = lib.types.int;
            default = 1000;
            description = "Max concurrent sessions cluster-wide";
          };
          fairnessStrategy = lib.mkOption {
            type = lib.types.enum [ "fifo" "lifo" "weighted" "priority" ];
            default = "weighted";
            description = "Session scheduling fairness strategy";
          };
          priorityClasses = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ "low" "normal" "high" "critical" ];
            description = "Priority class names";
          };
        };

        # ───────── Cost optimization / token budgeting ─────────
        tokenBudget = {
          enable = lib.mkEnableOption "Enable per-user token budgets";
          defaultDailyBudget = lib.mkOption {
            type = lib.types.int;
            default = 100000;
            description = "Default daily token budget per user";
          };
          warningThreshold = lib.mkOption {
            type = lib.types.float;
            default = 0.8;
            description = "Alert when this fraction of budget is consumed";
          };
          rolloverStrategy = lib.mkOption {
            type = lib.types.enum [ "none" "daily" "weekly" "monthly" ];
            default = "monthly";
            description = "How unused budget rolls over";
          };
        };

        # ───────── Graceful shutdown ─────────
        shutdown = {
          timeoutSec = lib.mkOption {
            type = lib.types.int;
            default = 30;
            description = "Graceful shutdown timeout";
          };
          drainSessions = lib.mkEnableOption "Wait for sessions to finish";
          saveState = lib.mkEnableOption "Save state on shutdown";
          notifyUsers = lib.mkEnableOption "Notify users of scheduled downtime";
        };

        # ───────── Security headers / CSP ─────────
        securityHeaders = {
          enable = lib.mkEnableOption "Enable security headers";
          contentSecurityPolicy = lib.mkOption {
            type = lib.types.str;
            default = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'";
            description = "Content Security Policy";
          };
          frameOptions = lib.mkOption {
            type = lib.types.enum [ "DENY" "SAMEORIGIN" ];
            default = "SAMEORIGIN";
            description = "X-Frame-Options";
          };
          corsOrigins = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
            example = [ "https://app.example.com" ];
            description = "Allowed CORS origins";
          };
        };

        # ───────── Plugin marketplace ─────────
        pluginMarketplace = {
          enable = lib.mkEnableOption "Enable plugin marketplace";
          registryUrl = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Marketplace registry URL";
          };
          autoUpdate = lib.mkEnableOption "Auto-update installed plugins";
          verifySignatures = lib.mkEnableOption "Verify plugin signatures before install";
        };
      };
    };
    default = { };
  };

  config = lib.mkIf cfg.enable {

    nixpkgs.config.allowUnfree = lib.mkDefault true;

    # ───────── Time Synchronization ─────────
    services.timesyncd = lib.mkIf cfg.timeSync.enable {
      enable = true;
      servers = cfg.timeSync.servers;
    };

    # ───────── System packages ─────────
    environment.systemPackages = lib.mkIf (!cfg.systemWide) [
      cfg.package
    ];

    # ───────── User/Group setup ─────────
    users.groups.${cfg.group} = lib.mkIf cfg.systemWide { };

    users.users.${cfg.user} = lib.mkIf cfg.systemWide {
      isNormalUser = true;
      home = cfg.dataDir;
      description = "Zeloo service account";
      group = cfg.group;
      shell = pkgs.bash;
    };

    # ───────── Main systemd service ─────────
    systemd.services.Zeloo = lib.mkIf cfg.systemWide {
      Unit = {
        Description = "Zeloo Agent Runtime (system-wide)";
        Documentation = [ "https://github.com/your-org/Zeloo" ];
        After = [ "network-online.target" ] ++ lib.optionals cfg.timeSync.enable [ "time-sync.target" ];
        Wants = [ "network-online.target" ];
        StartLimitIntervalSec = cfg.ha.startLimitIntervalSec;
        StartLimitBurst = cfg.ha.restartMaxAttempts;
      };

      Service = {
        Type = "notify";
        ExecStart = "${cfg.package}/bin/Zeloo run --system ${workspaceArgs}";
        ExecReload = "${pkgs.coreutils}/bin/kill -HUP $MAINPID";
        Restart = "on-failure";
        RestartSec = 5;
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = cfg.dataDir;

        StateDirectory = "Zeloo";
        logsDirectory = "Zeloo";
        cacheDirectory = "Zeloo";

        Environment = [
          "zeloo_DATA=${cfg.dataDir}"
          "zeloo_LOG=journald"
          "zeloo_LOG_LEVEL=${cfg.monitoring.logLevel}"
        ] ++ lib.optional (cfg.secrets.envFile != null)
          "EnvironmentFile=${cfg.secrets.envFile}";

        # Watchdog for HA
        WatchdogSec = lib.mkIf cfg.ha.enable cfg.ha.watchdogSec;
        NotifyAccess = lib.mkIf cfg.ha.enable "main";

        # Resource limits
        MemoryMax = cfg.resources.memoryMax;
        CPUQuota = cfg.resources.cpuQuota;

        # Security hardening
        Hardening = {
          ProtectSystem = "strict";
          ProtectHome = "read-only";
          PrivateTmp = true;
          PrivateDevices = true;
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          NoNewPrivileges = true;
          ProtectHostname = true;
          ProtectClock = true;
          ProtectProc = "invisible";
          ProcSubset = "pid";
        };

        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" "~@privileged" "~@resources" ];
      };

      Install.WantedBy = [ "multi-user.target" ];
    };

    # ───────── Health-check service (HA) ─────────
    systemd.services.Zeloo-healthcheck = lib.mkIf (cfg.systemWide && cfg.ha.enable) {
      Unit = {
        Description = "Zeloo Health Check";
        After = [ "Zeloo.service" ];
      };

      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo doctor --check-only --json";
        User = cfg.user;
        Group = cfg.group;

        # Notify main service on failure
        ExecCondition = "${pkgs.coreutils}/bin/test -S /run/Zeloo/healthcheck.sock";
      };
    };

    systemd.timers.Zeloo-healthcheck = lib.mkIf (cfg.systemWide && cfg.ha.enable) {
      Unit = {
        Description = "Periodic Zeloo Health Check Timer";
      };
      Timer = {
        OnBootSec = "60s";
        OnUnitActiveSec = "5min";
        AccuracySec = "10s";
      };
      Install.WantedBy = [ "timers.target" ];
    };

    # ───────── Backup timer + service ─────────
    systemd.timers.Zeloo-backup = lib.mkIf (cfg.systemWide && cfg.backup.enable) {
      Unit = {
        Description = "Zeloo Data Backup Timer";
        PartOf = "Zeloo-backup.service";
      };
      Timer = {
        OnCalendar = if cfg.backup.interval == "hourly" then "hourly"
          else if cfg.backup.interval == "weekly" then "weekly"
          else "daily";
        Persistent = true;
        RandomizedDelaySec = "5min";
      };
      Install.WantedBy = [ "timers.target" ];
    };

    systemd.services.Zeloo-backup = lib.mkIf (cfg.systemWide && cfg.backup.enable) {
      Unit = {
        Description = "Zeloo Data Backup Service";
        After = [ "Zeloo.service" ];
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo workspace archive --dest ${cfg.backup.destDir} --retention ${toString cfg.backup.retention}";
        User = cfg.user;
        Group = cfg.group;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        PrivateTmp = true;
      };
    };

    systemd.services.Zeloo-restore = lib.mkIf cfg.systemWide {
      Unit = {
        Description = "Zeloo Data Restore (manual)";
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo workspace restore --source ${cfg.backup.destDir}";
        User = cfg.user;
        Group = cfg.group;
        RemainAfterExit = true;
      };
    };

    # ───────── Prometheus metrics ─────────
    services.prometheus.exporters.Zeloo = lib.mkIf cfg.monitoring.prometheus.enable {
      enable = true;
      port = cfg.monitoring.prometheus.port;
    };

    # ───────── Firewall ─────────
    networking.firewall = lib.mkIf cfg.openPorts {
      allowedTCPPorts = [
        7860
        8765
        cfg.monitoring.prometheus.port
      ] ++ lib.optional cfg.reverseProxy.enable cfg.reverseProxy.port;
    };

    # ───────── Reverse proxy (nginx) ─────────
    services.nginx = lib.mkIf cfg.reverseProxy.enable {
      enable = true;

      virtualHosts.${cfg.reverseProxy.domain} = {
        listen = [
          {
            port = cfg.reverseProxy.port;
            ssl = cfg.reverseProxy.ssl != "none";
          }
        ];

        addHeaders = {
          "X-Frame-Options" = "SAMEORIGIN";
          "X-Content-Type-Options" = "nosniff";
          "X-XSS-Protection" = "1; mode=block";
          "Referrer-Policy" = "strict-origin-when-cross-origin";
        };

        locations."/" = {
          proxyPass = "http://127.0.0.1:7860";
          proxyWebsockets = cfg.reverseProxy.websockets;
          recommendedProxySettings = true;
          extraConfig = ''
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
          '';
        };

        locations."/api/ws" = lib.mkIf cfg.reverseProxy.websockets {
          proxyPass = "http://127.0.0.1:8765";
          proxyWebsockets = true;
          extraConfig = ''
            proxy_buffering off;
            proxy_cache off;
          '';
        };

        # SSL configuration
        enableACME = cfg.reverseProxy.ssl == "letsencrypt";
        sslCertificate = lib.mkIf (cfg.reverseProxy.ssl == "selfsigned")
          "/etc/ssl/certs/Zeloo-selfsigned.crt";
        sslCertificateKey = lib.mkIf (cfg.reverseProxy.ssl == "selfsigned")
          "/etc/ssl/private/Zeloo-selfsigned.key";

        security = {
          acme.email = lib.mkIf (cfg.reverseProxy.ssl == "letsencrypt") "admin@${cfg.reverseProxy.domain}";
        };
      };
    };

    security.acme = lib.mkIf (cfg.reverseProxy.enable && cfg.reverseProxy.ssl == "letsencrypt") {
      acceptTerms = true;
    };

    # ───────── Logging ─────────
    services.journald.extraConfig = lib.mkIf cfg.systemWide ''
      SystemMaxUse=500M
      SystemKeepFree=1G
      SystemMaxFileSize=50M
      MaxRetentionSec=2week
    '';

    # ───────── Multi-instance systemd units ─────────
    # Additional named instances (suffixed -<name>)
    systemd.services = lib.mkMerge [
      # Main instance ExecStart override when instances exist
      (lib.mkIf (cfg.systemWide && cfg.instances != { }) {
        Zeloo = {
          Service.ExecStart = lib.mkForce
            "${cfg.package}/bin/Zeloo run --system ${workspaceArgs}";
        };
      })

      # Named instances
      (lib.mkAttrs (lib.mapAttrs' (name: inst:
        lib.nameValuePair "Zeloo-${name}" (
          lib.mkIf inst.enable {
            Unit = {
              Description = "Zeloo Agent Runtime (instance: ${name})";
              After = [ "network-online.target" ];
              Wants = [ "network-online.target" ];
            };

            Service = {
              Type = "notify";
              ExecStart = "${cfg.package}/bin/Zeloo run --system \
                --data-dir ${inst.dataDir} \
                --port ${toString inst.port} \
                --model ${inst.model} \
                ${lib.concatMapStringsSep " " (ws: "--workspace ${ws}") inst.workspaces}";
              Restart = "on-failure";
              RestartSec = 5;
              User = cfg.user;
              Group = cfg.group;
              WorkingDirectory = inst.dataDir;

              Environment = [
                "zeloo_DATA=${inst.dataDir}"
                "zeloo_PORT=${toString inst.port}"
                "zeloo_LOG=journald"
              ];

              MemoryMax = cfg.resources.memoryMax;
              CPUQuota = cfg.resources.cpuQuota;

              Hardening = {
                ProtectSystem = "strict";
                ProtectHome = "read-only";
                PrivateTmp = true;
                NoNewPrivileges = true;
              };
            };

            Install.WantedBy = [ "multi-user.target" ];
          }
        )
      )
      (lib.attrNames cfg.instances)))
    ];

    # ───────── Cluster / Redis ─────────
    services.redis = lib.mkIf cfg.cluster.enable {
      enable = true;
      bind = cfg.cluster.redisHost;
      port = cfg.cluster.redisPort;
      enablePersistence = false;  # ephemeral cache
      maxMemory = "256mb";
      maxMemoryPolicy = "allkeys-lru";
    };

    users.groups.Zeloo-shared = lib.mkIf cfg.cluster.enable { };

    systemd.tmpfiles.rules = lib.mkIf cfg.cluster.enable [
      "d ${cfg.cluster.sharedStorage} 0750 ${cfg.user} Zeloo-shared - -"
      "d /run/Zeloo 0750 ${cfg.user} ${cfg.group} - -"
    ];

    # ───────── PostgreSQL (when selected) ─────────
    services.postgresql = lib.mkIf (cfg.database.backend == "postgres") {
      enable = true;
      package = pkgs.postgresql_15;
      enableTCPIP = true;
      listenAddresses = [ "127.0.0.1" ];
      port = cfg.database.postgres.port;

      ensureDatabases = [ cfg.database.postgres.database ];
      ensureUsers = [
        {
          name = cfg.database.postgres.user;
          ensureDBOwnership = true;
        }
      ];

      authentication = pkgs.lib.mkOverride 10 ''
        host ${cfg.database.postgres.database} ${cfg.database.postgres.user} 127.0.0.1/32 md5
      '';
    };

    # ───────── OpenTelemetry collector (optional) ─────────
    services.opentelemetry-collector = lib.mkIf cfg.tracing.enable {
      enable = true;
      settings = {
        receivers.otlp = {
          protocols.grpc = {
            endpoint = "0.0.0.0:4317";
          };
        };
        processors.batch = { };
        exporters.otlp = {
          endpoint = cfg.tracing.endpoint;
        };
        service = {
          pipelines.traces = {
            receivers = [ "otlp" ];
            processors = [ "batch" ];
            exporters = [ "otlp" ];
          };
        };
      };
    };

    # ───────── Container runtime (Podman quadlet) ─────────
    virtualisation.podman = lib.mkIf cfg.container.enable {
      enable = true;
      dockerCompat = true;
      defaultNetwork.settings.dns_enabled = true;
    };

    systemd.user.services.Zeloo-container = lib.mkIf (cfg.container.enable && !cfg.systemWide) {
      Unit = {
        Description = "Zeloo Container (rootless)";
        After = [ "podman.service" ];
        Wants = [ "podman.service" ];
      };

      Service = {
        Type = "notify";
        ExecStartPre = "${pkgs.podman}/bin/podman pull ${cfg.container.image}";
        ExecStart = "${pkgs.podman}/bin/podman run --rm \
          --name Zeloo \
          --network ${cfg.container.network} \
          ${lib.optionalString cfg.container.userNamespace "--userns=keep-id"} \
          -v ${cfg.dataDir}:/var/lib/Zeloo:rw \
          -v /run/Zeloo:/run/Zeloo:rw \
          -e zeloo_DATA=/var/lib/Zeloo \
          ${cfg.container.image}";
        ExecStop = "${pkgs.podman}/bin/podman stop Zeloo";
        Restart = "on-failure";
        RestartSec = 10;
      };

      Install.WantedBy = [ "default.target" ];
    };

    # ───────── Auto-update timer (containers) ─────────
    systemd.services.Zeloo-image-update = lib.mkIf (cfg.container.enable && cfg.container.autoUpdate) {
      Unit = {
        Description = "Zeloo Container Image Auto-Update";
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${pkgs.podman}/bin/podman pull ${cfg.container.image}:${cfg.container.imageTag}";
      };
    };

    systemd.timers.Zeloo-image-update = lib.mkIf (cfg.container.enable && cfg.container.autoUpdate) {
      Unit = { Description = "Zeloo Image Update Timer"; };
      Timer = {
        OnCalendar = "daily";
        RandomizedDelaySec = "1h";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    # ───────── SOPS secrets decryption ─────────
    sops = lib.mkIf (cfg.secrets.sopsFile != null) {
      defaultSopsFile = cfg.secrets.sopsFile;
      age.sshKeyPaths = lib.optional (cfg.secrets.ageKeyFile != null) cfg.secrets.ageKeyFile;
      secrets = {
        "Zeloo/api_keys" = {
          owner = cfg.user;
          group = cfg.group;
          mode = "0600";
          path = "${cfg.dataDir}/api_keys.json";
        };
      };
    };

    # ───────── Rate limiting ─────────
    services.fail2ban.jails.Zeloo = lib.mkIf cfg.rateLimit.enable {
      enabled = true;
      filter = "Zeloo-ratelimit";
      logpath = "/var/log/Zeloo/*.log";
      maxretry = cfg.rateLimit.requestsPerMinute;
      findtime = 60;
      bantime = 3600;
    };

    # ───────── TLS termination (HAProxy) ─────────
    services.haproxy = lib.mkIf cfg.tls.enable {
      enable = true;

      globalConfig = ''
        ssl-default-bind-options ssl-min-ver ${if cfg.tls.minVersion == "1.3" then "TLSv1.3" else "TLSv1.2"} no-sslv3
        ssl-default-bind-ciphersuites TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256
      '';

      frontend = {
        Zeloo-tls = {
          mode = "tcp";
          bind = [
            {
              address = "0.0.0.0";
              port = 443;
              ssl = true;
              cert = if cfg.tls.certFile != null then toString cfg.tls.certFile else null;
              ciphers = "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM";
              alpn = [ "h2" "http/1.1" ];
            }
          ];
          extraConfig = lib.optionalString cfg.tls.hsts ''
            http-response set-header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
          '';
          defaultBackend = "Zeloo-backend";
        };
      };

      backend = {
        Zeloo-backend = {
          mode = "tcp";
          servers = [
            {
              name = "Zeloo-primary";
              address = "127.0.0.1";
              port = 7860;
              check = true;
            }
          ] ++ lib.optional cfg.canary.enable {
            name = "Zeloo-canary";
            address = "127.0.0.1";
            port = 7862;
            check = true;
            weight = cfg.canary.weight;
          };
        };
      };
    };

    # ───────── Mutual TLS (mTLS) client cert ─────────
    environment.etc."Zeloo/ca.crt".source = lib.mkIf cfg.tls.clientCertAuth (
      if cfg.tls.certFile != null then toString cfg.tls.certFile else pkgs.runCommand "dummy" { } "mkdir -p $out"
    );

    # ───────── Canary deployment slot ─────────
    systemd.services.Zeloo-canary = lib.mkIf cfg.canary.enable {
      Unit = {
        Description = "Zeloo Canary Slot";
        After = [ "Zeloo.service" ];
      };
      Service = {
        Type = "notify";
        ExecStart = "${cfg.package}/bin/Zeloo run --system --canary --port 7862 ${workspaceArgs}";
        Restart = "on-failure";
        RestartSec = 5;
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = "${cfg.dataDir}-canary";

        StateDirectory = "Zeloo-canary";

        Environment = [
          "zeloo_DATA=${cfg.dataDir}-canary"
          "zeloo_PORT=7862"
          "zeloo_LOG=journald"
        ];

        MemoryMax = cfg.resources.memoryMax;
        CPUQuota = cfg.resources.cpuQuota;
      };

      Install.WantedBy = [ "multi-user.target" ];
    };

    systemd.timers.Zeloo-canary-healthcheck = lib.mkIf cfg.canary.enable {
      Unit = { Description = "Zeloo Canary Health Check"; };
      Timer = {
        OnUnitActiveSec = "${toString cfg.canary.healthCheckInterval}s";
        AccuracySec = "5s";
      };
      Install.WantedBy = [ "timers.target" ];
    };

    systemd.services.Zeloo-canary-healthcheck = lib.mkIf cfg.canary.enable {
      Unit = { Description = "Zeloo Canary Health Check Service"; };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo doctor --check-only --json";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    systemd.services.Zeloo-canary-promote = lib.mkIf (cfg.canary.enable && cfg.canary.autoPromote) {
      Unit = { Description = "Promote Zeloo Canary to Production"; };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo canary promote";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    # ───────── A/B testing configuration ─────────
    environment.etc."Zeloo/ab_tests.json".text = lib.mkIf cfg.abTest.enable (
      builtins.toJSON {
        experiments = cfg.abTest.experiments;
        enabled = true;
      }
    );

    # ───────── Kubernetes operator deployment ─────────
    kubernetes.helm.charts.Zeloo-operator = lib.mkIf cfg.kubernetes.enable {
      chart = if cfg.kubernetes.chart != null
        then toString cfg.kubernetes.chart
        else pkgs.fetchurl {
          url = "https://github.com/your-org/Zeloo-operator/releases/latest/download/Zeloo-operator-0.1.0.tgz";
          sha256 = "";
        };
      values = {
        namespace = cfg.kubernetes.namespace;
        replicaCount = cfg.kubernetes.replicas;
        image.repository = "ghcr.io/your-org/Zeloo-operator";
        image.tag = "latest";
      };
    };

    # ───────── Backup encryption (age) ─────────
    systemd.services.Zeloo-backup = lib.mkIf (cfg.systemWide && cfg.backup.enable) (
      let
        backupExecStart = "${cfg.package}/bin/Zeloo workspace archive --dest ${cfg.backup.destDir} --retention ${toString cfg.backup.retention}"
          + lib.optionalString cfg.backupEncryption.enable
            " | ${pkgs.age}/bin/age -e -r ${if cfg.backupEncryption.publicKeyFile != null then toString cfg.backupEncryption.publicKeyFile else "/dev/null"} > ${cfg.backup.destDir}/latest.tar.zst.age";
      in
      {
        Unit = {
          Description = "Zeloo Data Backup Service (encrypted)";
          After = [ "Zeloo.service" ];
        };
        Service = {
          Type = "oneshot";
          ExecStart = backupExecStart;
          User = cfg.user;
          Group = cfg.group;
          ProtectSystem = "strict";
          ProtectHome = "read-only";
          PrivateTmp = true;
        };
      }
    );

    # ───────── Cost control ─────────
    systemd.services.Zeloo-cost-monitor = lib.mkIf cfg.costControl.enable {
      Unit = {
        Description = "Zeloo Cost Control Monitor";
      };
      Service = {
        Type = "notify";
        ExecStart = "${cfg.package}/bin/Zeloo cost-monitor \
          --budget ${toString cfg.costControl.monthlyBudgetUSD} \
          --alert-threshold ${toString cfg.costControl.alertThreshold} \
          ${lib.optionalString cfg.costControl.enforceHardLimit "--hard-limit"}";
        Restart = "always";
        RestartSec = 60;
        User = cfg.user;
        Group = cfg.group;
      };
      Install.WantedBy = [ "multi-user.target" ];
    };

    systemd.timers.Zeloo-cost-report = lib.mkIf cfg.costControl.enable {
      Unit = { Description = "Zeloo Cost Report Generator"; };
      Timer = {
        OnCalendar = "weekly";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    systemd.services.Zeloo-cost-report = lib.mkIf cfg.costControl.enable {
      Unit = { Description = "Zeloo Cost Report Service"; };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo cost-report --json --output /var/log/Zeloo/cost-report.json";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    # ───────── Authentication integration ─────────
    services.nginx.virtualHosts.Zeloo-auth = lib.mkIf (cfg.auth.method == "ldap" && cfg.auth.ldapHost != null) {
      enableACME = false;
      locations."/" = {
        proxyPass = "http://127.0.0.1:7860";
        extraConfig = ''
          auth_basic "Zeloo";
          auth_basic_user_file ${pkgs.writeText "Zeloo-htpasswd" ""};
        '';
      };
    };

    services.nginx.virtualHosts.Zeloo-auth = lib.mkIf (cfg.auth.method == "oauth2" || cfg.auth.method == "oidc") {
      enableACME = false;
      locations."/oauth2/" = {
        proxyPass = "http://127.0.0.1:7860/oauth2/";
      };
    };

    # ───────── Audit logging ─────────
    services.rsyslogd = lib.mkIf cfg.audit.enable {
      enable = true;
      defaultConfig = false;
      configFile = pkgs.writeText "Zeloo-audit.conf" ''
        module(load="imuxsock")
        module(load="omfile")

        template(name="ZelooAuditFormat" type="string"
          string="%timegenerated% %syslogtag% %msg%\n")

        ruleset(name="Zeloo-audit") {
          action(type="omfile"
                 file="${cfg.audit.logFile}"
                 template="ZelooAuditFormat"
                 flushOnTXEnd="on")
        }

        input(type="imuxsock" Socket="/run/Zeloo/audit.sock" Ruleset="Zeloo-audit")
      '';
    };

    systemd.tmpfiles.rules = [
      "f /run/Zeloo/audit.sock 0660 ${cfg.user} ${cfg.group} - -"
    ] ++ lib.optional cfg.audit.enable
      "d /var/log/Zeloo 0750 ${cfg.user} ${cfg.group} - -";

    # ───────── Logrotate for audit logs ─────────
    services.logrotate.settings.Zeloo = lib.mkIf cfg.audit.enable {
      files = [ cfg.audit.logFile ];
      frequency = "daily";
      rotate = cfg.audit.retentionDays;
      compress = true;
      missingok = true;
      notifempty = true;
      postrotate = ''
        systemctl reload rsyslog.service || true
      '';
    };

    # ───────── Disaster Recovery ─────────
    systemd.services.Zeloo-dr-sync = lib.mkIf cfg.disasterRecovery.enable {
      Unit = {
        Description = "Zeloo Disaster Recovery Sync";
        After = [ "Zeloo.service" ];
        Requires = [ "Zeloo.service" ];
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo dr sync \
          --primary ${if cfg.disasterRecovery.primaryHost != null then cfg.disasterRecovery.primaryHost else "127.0.0.1"} \
          --replica ${if cfg.disasterRecovery.replicaHost != null then cfg.disasterRecovery.replicaHost else "127.0.0.1"} \
          --rpo ${toString cfg.disasterRecovery.rpoSec}";
        User = cfg.user;
        Group = cfg.group;
        ProtectSystem = "strict";
      };
    };

    systemd.timers.Zeloo-dr-sync = lib.mkIf cfg.disasterRecovery.enable {
      Unit = { Description = "Zeloo DR Sync Timer"; };
      Timer = {
        OnUnitActiveSec = "${toString cfg.disasterRecovery.syncIntervalSec}s";
        AccuracySec = "5s";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    systemd.services.Zeloo-dr-promote = lib.mkIf (cfg.disasterRecovery.enable && cfg.disasterRecovery.autoFailover) {
      Unit = {
        Description = "Zeloo DR Auto-Promote to Primary";
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo dr promote";
        User = cfg.user;
        Group = cfg.group;
        ExecCondition = "${pkgs.coreutils}/bin/test ! -f /var/lib/Zeloo/.primary-marker";
      };
    };

    systemd.paths.Zeloo-dr-watcher = lib.mkIf (cfg.disasterRecovery.enable && cfg.disasterRecovery.autoFailover) {
      Unit = {
        Description = "Watch for primary failure";
      };
      Path = {
        PathExists = "/var/lib/Zeloo/.primary-down";
      };
      Unit.X-StartAfter = "Zeloo-dr-promote.service";
    };

    # ───────── GitOps config sync ─────────
    systemd.services.Zeloo-gitops-sync = lib.mkIf cfg.gitOps.enable {
      Unit = {
        Description = "Zeloo GitOps Config Sync";
        After = [ "network-online.target" ];
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo config sync \
          --repo ${if cfg.gitOps.repoUrl != null then cfg.gitOps.repoUrl else ""} \
          --branch ${cfg.gitOps.branch} \
          ${lib.optionalString (cfg.gitOps.sshKeyFile != null) "--ssh-key ${toString cfg.gitOps.sshKeyFile}"}";
        WorkingDirectory = cfg.dataDir;
        User = cfg.user;
        Group = cfg.group;
      };
    };

    systemd.timers.Zeloo-gitops-sync = lib.mkIf cfg.gitOps.enable {
      Unit = { Description = "Zeloo GitOps Sync Timer"; };
      Timer = {
        OnUnitActiveSec = "${toString cfg.gitOps.pollIntervalSec}s";
        AccuracySec = "10s";
      };
      Install.WantedBy = [ "timers.target" ];
    };

    # ───────── Service Mesh sidecar injection ─────────
    kubernetes.annotations = lib.mkIf (cfg.serviceMesh.enable && cfg.serviceMesh.injectSidecar) {
      "linkerd.io/inject" = if cfg.serviceMesh.type == "linkerd" then "enabled" else null;
      "istio.io/inject" = if cfg.serviceMesh.type == "istio" then "true" else null;
      "consul.hashicorp.com/connect-inject" = if cfg.serviceMesh.type == "consul" then "true" else null;
    };

    environment.etc."Zeloo/service-mesh.json".text = lib.mkIf cfg.serviceMesh.enable (
      builtins.toJSON {
        mesh = cfg.serviceMesh.type;
        mtls = cfg.serviceMesh.mtls;
      }
    );

    # ───────── Multi-region replication ─────────
    environment.etc."Zeloo/geo.json".text = lib.mkIf cfg.geoReplication.enable (
      builtins.toJSON {
        region = cfg.geoReplication.currentRegion;
        regions = cfg.geoReplication.regions;
        strategy = cfg.geoReplication.replicationStrategy;
      }
    );

    # ───────── Webhook publisher ─────────
    environment.etc."Zeloo/webhooks.json".text = lib.mkIf cfg.webhooks.enable (
      builtins.toJSON {
        endpoints = cfg.webhooks.endpoints;
      }
    );
    environment.etc."Zeloo/webhooks.json".mode = "0640";

    # ───────── Plugin sandboxing ─────────
    environment.etc."Zeloo/plugin-security.json".text = builtins.toJSON {
      sandbox = cfg.pluginSecurity.sandbox;
      networkAccess = cfg.pluginSecurity.networkAccess;
      fileSystemAccess = cfg.pluginSecurity.fileSystemAccess;
      cpuLimit = cfg.pluginSecurity.cpuLimit;
      memoryLimit = cfg.pluginSecurity.memoryLimit;
    };

    # ───────── Notification channels ─────────
    environment.etc."Zeloo/notifications.json".text = builtins.toJSON {
      slack = {
        enabled = cfg.notifications.slack.enable;
        webhookUrl = cfg.notifications.slack.webhookUrl;
      };
      email = {
        enabled = cfg.notifications.email.enable;
        smtpHost = cfg.notifications.email.smtpHost;
        from = cfg.notifications.email.from;
        to = cfg.notifications.email.to;
      };
      pagerduty = {
        enabled = cfg.notifications.pagerduty.enable;
        integrationKey = cfg.notifications.pagerduty.integrationKey;
      };
    };
    environment.etc."Zeloo/notifications.json".mode = "0640";

    # ───────── Quota management ─────────
    environment.etc."Zeloo/quota.json".text = builtins.toJSON cfg.quota;

    # ───────── Custom branding ─────────
    environment.etc."Zeloo/branding.json".text = builtins.toJSON {
      name = cfg.branding.name;
      logoUrl = cfg.branding.logoUrl;
      primaryColor = cfg.branding.primaryColor;
      hasCustomCss = cfg.branding.customCss != null;
    };

    # ───────── Feature flags ─────────
    environment.etc."Zeloo/feature_flags.json".text = lib.mkIf cfg.featureFlags.enable (
      builtins.toJSON {
        enabled = true;
        flags = cfg.featureFlags.flags;
      }
    );

    # ───────── SLO monitoring ─────────
    environment.etc."Zeloo/slo.json".text = lib.mkIf cfg.slo.enable (
      builtins.toJSON {
        availability = cfg.slo.availability;
        latencyP99Ms = cfg.slo.latencyP99Ms;
        errorBudget = cfg.slo.errorBudget;
        windowDays = cfg.slo.windowDays;
      }
    );

    # ───────── Chaos engineering ─────────
    environment.etc."Zeloo/chaos.json".text = lib.mkIf cfg.chaos.enable (
      builtins.toJSON {
        enabled = cfg.chaos.enable;
        latencyInjectionMs = cfg.chaos.latencyInjectionMs;
        errorRate = cfg.chaos.errorRate;
        killSwitch = cfg.chaos.killSwitch;
      }
    );

    systemd.timers.Zeloo-chaos = lib.mkIf (cfg.chaos.enable && cfg.chaos.scheduleCron != "") {
      Unit = { Description = "Zeloo Chaos Experiment Timer"; };
      Timer = {
        OnCalendar = cfg.chaos.scheduleCron;
        RandomizedDelaySec = "30s";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    systemd.services.Zeloo-chaos = lib.mkIf (cfg.chaos.enable && cfg.chaos.scheduleCron != "") {
      Unit = {
        Description = "Zeloo Chaos Experiment Service";
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo chaos run";
        User = cfg.user;
        Group = cfg.group;
        ProtectSystem = "strict";
      };
    };

    # ───────── CI/CD integration ─────────
    systemd.paths.Zeloo-ci-deploy = lib.mkIf (cfg.ci.autoDeploy && cfg.ci.webhookUrl != null) {
      Unit = { Description = "Watch for CI/CD deploy triggers"; };
      Path = {
        PathExists = "/run/Zeloo/.deploy-pending";
      };
      Unit.X-StartAfter = "Zeloo-ci-deploy.service";
    };

    systemd.services.Zeloo-ci-deploy = lib.mkIf (cfg.ci.autoDeploy && cfg.ci.webhookUrl != null) {
      Unit = { Description = "Zeloo CI/CD Deploy Service"; };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo deploy \
          --provider ${cfg.ci.provider} \
          --branch ${cfg.ci.deployBranch} \
          --webhook ${cfg.ci.webhookUrl}";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    # ───────── Compliance / privacy ─────────
    environment.etc."Zeloo/compliance.json".text = builtins.toJSON {
      framework = cfg.compliance.framework;
      dataRetentionDays = cfg.compliance.dataRetentionDays;
      rightToBeForgotten = cfg.compliance.rightToBeForgotten;
      dataResidencyRegion = cfg.compliance.dataResidencyRegion;
      piiRedaction = cfg.compliance.piiRedaction;
    };

    systemd.timers.Zeloo-data-purge = lib.mkIf (cfg.compliance.dataRetentionDays > 0) {
      Unit = { Description = "Zeloo Data Retention Purge"; };
      Timer = {
        OnCalendar = "daily";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    systemd.services.Zeloo-data-purge = lib.mkIf (cfg.compliance.dataRetentionDays > 0) {
      Unit = { Description = "Zeloo Data Retention Purge Service"; };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo data purge --older-than ${toString cfg.compliance.dataRetentionDays}d";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    # ───────── Performance budgets ─────────
    environment.etc."Zeloo/perf_budget.json".text = builtins.toJSON cfg.perfBudget;

    # ───────── Streaming output config ─────────
    environment.etc."Zeloo/streaming.json".text = builtins.toJSON {
      bufferSizeKb = cfg.streaming.bufferSizeKb;
      flushIntervalMs = cfg.streaming.flushIntervalMs;
      compression = cfg.streaming.compression;
    };

    # ───────── Observability exporters ─────────
    environment.etc."Zeloo/exporters.json".text = builtins.toJSON {
      otlp = {
        enabled = cfg.observabilityExporters.otlp.enable;
        endpoint = cfg.observabilityExporters.otlp.endpoint;
      };
      prometheus = {
        enabled = cfg.observabilityExporters.prometheus.enable;
        port = cfg.observabilityExporters.prometheus.port;
      };
      jaeger = {
        enabled = cfg.observabilityExporters.jaeger.enable;
        endpoint = cfg.observabilityExporters.jaeger.endpoint;
      };
      loki = {
        enabled = cfg.observabilityExporters.loki.enable;
        endpoint = cfg.observabilityExporters.loki.endpoint;
      };
    };

    # ───────── AI safety controls ─────────
    environment.etc."Zeloo/ai_safety.json".text = builtins.toJSON {
      enabled = cfg.aiSafety.enable;
      contentFilter = cfg.aiSafety.contentFilter;
      promptInjectionDetection = cfg.aiSafety.promptInjectionDetection;
      jailbreakDetection = cfg.aiSafety.jailbreakDetection;
      outputSanitization = cfg.aiSafety.outputSanitization;
      maxContextLength = cfg.aiSafety.maxContextLength;
    };

    # ───────── Event sourcing ─────────
    environment.etc."Zeloo/event_sourcing.json".text = lib.mkIf cfg.eventSourcing.enable (
      builtins.toJSON {
        enabled = true;
        store = cfg.eventSourcing.store;
        snapshotInterval = cfg.eventSourcing.snapshotInterval;
        retentionDays = cfg.eventSourcing.retentionDays;
      }
    );

    # ───────── CQRS ─────────
    environment.etc."Zeloo/cqrs.json".text = lib.mkIf cfg.cqrs.enable (
      builtins.toJSON {
        enabled = true;
        readReplicas = cfg.cqrs.readReplicas;
        cacheBackend = cfg.cqrs.cacheBackend;
        cacheTtlSec = cfg.cqrs.cacheTtlSec;
      }
    );

    # ───────── Model governance ─────────
    environment.etc."Zeloo/model_governance.json".text = builtins.toJSON {
      allowlist = cfg.modelGovernance.allowlist;
      blocklist = cfg.modelGovernance.blocklist;
      requireApproval = cfg.modelGovernance.requireApproval;
      costCeilingPerCall = cfg.modelGovernance.costCeilingPerCall;
      latencyCeilingMs = cfg.modelGovernance.latencyCeilingMs;
    };

    # ───────── Workspace templates ─────────
    environment.etc."Zeloo/workspace_templates.json".text = lib.mkIf cfg.workspaceTemplates.enable (
      builtins.toJSON {
        enabled = true;
        registry = cfg.workspaceTemplates.registry;
        autoSync = cfg.workspaceTemplates.autoSync;
        defaultTemplates = cfg.workspaceTemplates.defaultTemplates;
      }
    );

    systemd.services.Zeloo-template-sync = lib.mkIf (cfg.workspaceTemplates.enable && cfg.workspaceTemplates.autoSync) {
      Unit = { Description = "Zeloo Workspace Template Sync"; };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo workspace templates sync";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    systemd.timers.Zeloo-template-sync = lib.mkIf (cfg.workspaceTemplates.enable && cfg.workspaceTemplates.autoSync) {
      Unit = { Description = "Zeloo Template Sync Timer"; };
      Timer = {
        OnCalendar = "hourly";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    # ───────── Federated learning ─────────
    environment.etc."Zeloo/federated.json".text = lib.mkIf cfg.federatedLearning.enable (
      builtins.toJSON {
        enabled = true;
        coordinator = cfg.federatedLearning.coordinator;
        privacyLevel = cfg.federatedLearning.privacyLevel;
        noiseEpsilon = cfg.federatedLearning.noiseEpsilon;
      }
    );

    # ───────── Cache policy ─────────
    environment.etc."Zeloo/cache_policy.json".text = builtins.toJSON cfg.cachePolicy;

    # ───────── I18n / l10n ─────────
    environment.etc."Zeloo/i18n.json".text = builtins.toJSON {
      defaultLocale = cfg.i18n.defaultLocale;
      supportedLocales = cfg.i18n.supportedLocales;
      dateFormat = cfg.i18n.dateFormat;
      timezone = cfg.i18n.timezone;
    };

    # ───────── Model adapters ─────────
    environment.etc."Zeloo/adapters.json".text = lib.mkIf cfg.modelAdapters.enable (
      builtins.toJSON {
        enabled = true;
        directory = cfg.modelAdapters.directory;
        hotReload = cfg.modelAdapters.hotReload;
      }
    );

    systemd.paths.Zeloo-adapter-reload = lib.mkIf (cfg.modelAdapters.enable && cfg.modelAdapters.hotReload) {
      Unit = { Description = "Watch for adapter file changes"; };
      Path = {
        PathExistsGlob = lib.optionalString (cfg.modelAdapters.directory != null) "${toString cfg.modelAdapters.directory}/*.py";
      };
      Unit.X-StartAfter = "Zeloo-adapter-reload.service";
    };

    systemd.services.Zeloo-adapter-reload = lib.mkIf (cfg.modelAdapters.enable && cfg.modelAdapters.hotReload) {
      Unit = { Description = "Zeloo Adapter Hot Reload"; };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo adapters reload";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    # ───────── Testing mode ─────────
    environment.etc."Zeloo/testing.json".text = builtins.toJSON {
      testMode = cfg.testing.enableTestMode;
      coverageThreshold = cfg.testing.coverageThreshold;
      parallelJobs = cfg.testing.parallelJobs;
    };

    # ───────── Database migrations ─────────
    environment.etc."Zeloo/migrations.json".text = builtins.toJSON {
      autoMigrate = cfg.dbMigrations.autoMigrate;
      backupBeforeMigrate = cfg.dbMigrations.backupBeforeMigrate;
      timeoutSec = cfg.dbMigrations.timeoutSec;
      lockTimeoutSec = cfg.dbMigrations.lockTimeoutSec;
    };

    systemd.services.Zeloo-db-migrate = lib.mkIf cfg.dbMigrations.autoMigrate {
      Unit = {
        Description = "Zeloo Database Migration";
        Before = [ "Zeloo.service" ];
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/Zeloo db migrate --timeout ${toString cfg.dbMigrations.timeoutSec}";
        User = cfg.user;
        Group = cfg.group;
      };
    };

    # ───────── Token bucket rate limiter ─────────
    environment.etc."Zeloo/token_bucket.json".text = lib.mkIf cfg.tokenBucket.enable (
      builtins.toJSON {
        enabled = true;
        capacity = cfg.tokenBucket.capacity;
        refillRatePerSec = cfg.tokenBucket.refillRatePerSec;
        burstMultiplier = cfg.tokenBucket.burstMultiplier;
      }
    );

    # ───────── Circuit breaker ─────────
    environment.etc."Zeloo/circuit_breaker.json".text = lib.mkIf cfg.circuitBreaker.enable (
      builtins.toJSON {
        enabled = true;
        failureThreshold = cfg.circuitBreaker.failureThreshold;
        resetTimeoutSec = cfg.circuitBreaker.resetTimeoutSec;
        halfOpenRequests = cfg.circuitBreaker.halfOpenRequests;
      }
    );

    # ───────── Progressive rollout ─────────
    environment.etc."Zeloo/rollout.json".text = builtins.toJSON {
      strategy = cfg.rollout.strategy;
      batchSize = cfg.rollout.batchSize;
      batchDelaySec = cfg.rollout.batchDelaySec;
      healthCheckTimeout = cfg.rollout.healthCheckTimeout;
      abortOnFailure = cfg.rollout.abortOnFailure;
    };

    # ───────── Resource scheduling ─────────
    environment.etc."Zeloo/scheduling.json".text = builtins.toJSON {
      maxConcurrentSessions = cfg.scheduling.maxConcurrentSessions;
      fairnessStrategy = cfg.scheduling.fairnessStrategy;
      priorityClasses = cfg.scheduling.priorityClasses;
    };

    # ───────── Token budget per user ─────────
    environment.etc."Zeloo/token_budget.json".text = lib.mkIf cfg.tokenBudget.enable (
      builtins.toJSON {
        enabled = true;
        defaultDailyBudget = cfg.tokenBudget.defaultDailyBudget;
        warningThreshold = cfg.tokenBudget.warningThreshold;
        rolloverStrategy = cfg.tokenBudget.rolloverStrategy;
      }
    );

    systemd.timers.Zeloo-budget-rollover = lib.mkIf cfg.tokenBudget.enable {
      Unit = { Description = "Zeloo Token Budget Rollover"; };
      Timer = {
        OnCalendar = if cfg.tokenBudget.rolloverStrategy == "daily" then "daily"
          else if cfg.tokenBudget.rolloverStrategy == "weekly" then "weekly"
          else "monthly";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    # ───────── Graceful shutdown ─────────
    environment.etc."Zeloo/shutdown.json".text = builtins.toJSON {
      timeoutSec = cfg.shutdown.timeoutSec;
      drainSessions = cfg.shutdown.drainSessions;
      saveState = cfg.shutdown.saveState;
      notifyUsers = cfg.shutdown.notifyUsers;
    };

    # ───────── Security headers / CSP ─────────
    environment.etc."Zeloo/security_headers.json".text = lib.mkIf cfg.securityHeaders.enable (
      builtins.toJSON {
        enabled = true;
        contentSecurityPolicy = cfg.securityHeaders.contentSecurityPolicy;
        frameOptions = cfg.securityHeaders.frameOptions;
        corsOrigins = cfg.securityHeaders.corsOrigins;
      }
    );

    # ───────── Plugin marketplace ─────────
    environment.etc."Zeloo/marketplace.json".text = lib.mkIf cfg.pluginMarketplace.enable (
      builtins.toJSON {
        enabled = true;
        registryUrl = cfg.pluginMarketplace.registryUrl;
        autoUpdate = cfg.pluginMarketplace.autoUpdate;
        verifySignatures = cfg.pluginMarketplace.verifySignatures;
      }
    );

    systemd.timers.Zeloo-plugin-update = lib.mkIf (cfg.pluginMarketplace.enable && cfg.pluginMarketplace.autoUpdate) {
      Unit = { Description = "Zeloo Plugin Marketplace Update Timer"; };
      Timer = {
        OnCalendar = "daily";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };

    # ───────── Documentation ─────────
    documentation.nixos.enable = lib.mkDefault false;
    documentation.man.enable = lib.mkDefault false;
  };
}

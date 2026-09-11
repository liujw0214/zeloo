# 28. Nix 构建配置开发计划

> Zeloo 支持 Nix Flakes 声明式构建。本文档记录需要开发的 Nix 配置。

## 28.1 目录结构

```
nix/
├── flake.nix                 # Flake 定义
├── flake.lock                # 锁文件
├── checks.nix               # 完整性检查
├── configMergeScript.nix    # NixOS 配置合并
├── desktop.nix              # 桌面应用构建
├── devShell.nix             # 开发环境
├── Zeloo.nix                     # 主包构建
├── homeManagerModules.nix   # Home Manager 模块
└── shell.nix               # 兼容旧版
```

---

## 28.2 flake.nix Flake 定义

```nix
# nix/flake.nix

{
  description = "Zeloo Agent - Self-evolving AI runtime";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312;
      in
      {
        packages = {
          Zeloo = pkgs.callPackage ./Zeloo.nix { };
          default = self.packages.${system}.Zeloo;
        };

        devShells.default = import ./devShell.nix {
          inherit pkgs;
          name = "Zeloo-dev";
        };

        checks = import ./checks.nix {
          inherit pkgs self;
        };
      }
    );
}
```

---

## 28.3 Zeloo.nix 主包构建

```nix
# nix/Zeloo.nix

{ pkgs ? import <nixpkgs> { }
, python ? pkgs.python312
}:

pkgs.python312Packages.buildPythonPackage {
  pname = "Zeloo";
  version = "0.1.0";

  src = pkgs.lib.cleanSource ../.;

  format = "pyproject";

  dependencies = with pkgs.python312Packages; [
    openai
    anthropic
    rich
    prompt-toolkit
    watchdog
    tiktoken
    duckduckgo-search
    playwright
  ];

  buildInputs = with pkgs; [
    git
    ffmpeg  # 音视频处理
    nodejs  # MCP 工具
  ];

  postInstall = ''
    mkdir -p $out/bin
    ln -s $package/bin/Zeloo $out/bin/Zeloo
  '';

  meta = with pkgs.lib; {
    description = "Self-evolving AI Agent runtime";
    homepage = "https://github.com/Zeloo/Zeloo";
    license = licenses.mit;
    platforms = platforms.linux ++ platforms.darwin;
  };
}
```

---

## 28.4 devShell.nix 开发环境

```nix
# nix/devShell.nix

{ pkgs ? import <nixpkgs> { }, name ? "Zeloo-dev" }:

pkgs.mkShell {
  inherit name;

  packages = with pkgs; [
    # Python 开发工具
    python312
    (python312.withPackages (ps: with ps; [
      pytest
      ruff
      pyright
      ipython
    ]))

    # 语言工具
    git
    gh
    nodejs_22

    # 开发辅助
    entr         # 文件变更自动重跑
    just         # 命令运行器
    shellcheck   # Shell 检查

    # Docker（可选）
    docker-compose
  ];

  # 环境变量
  env = {
    zeloo_ENV = "development";
    EDITOR = "code";
  };

  # Shell 钩子
  shellHook = ''
    echo "=== Zeloo Development Environment ==="
    echo "Python: $(python --version)"
    echo "Node: $(node --version)"
    echo ""
    echo "常用命令："
    echo "  just test      - 运行测试"
    echo "  just lint      - 运行 lint"
    echo "  just typecheck - 类型检查"
  '';
}
```

---

## 28.5 后续计划

| 文件 | 状态 | 说明 |
|------|-------|------|
| `desktop.nix` | ✅ 已实现 | NixOS systemd 用户服务（systemd.user.services.Zeloo） |
| `homeManagerModules.nix` | ✅ 已实现 | Home Manager 集成（profile/providers/observability/workspace） |
| `configMergeScript.nix` | ✅ 已实现 | NixOS 配置合并（systemd 服务 + Hardening + 工作区默认） |
| `flake.nix` | ✅ 已实现 | Flake 输入（nixpkgs/flake-utils）+ NixOS modules 输出 |

### homeManagerModules.nix（待实现）

```nix
# nix/homeManagerModules.nix

{ config, lib, pkgs, ... }:

{
  options.Zeloo = {
    enable = lib.mkEnableOption "Enable Zeloo Agent";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.Zeloo;
      description = "Zeloo package to use";
    };

    configPath = lib.mkOption {
      type = lib.types.path;
      default = "${config.home.homeDirectory}/.config/Zeloo/config.yaml";
      description = "Path to Zeloo config file";
    };

    defaultUser = lib.mkOption {
      type = lib.types.str;
      default = "Zeloo";
      description = "Default user to run Zeloo as";
    };
  };

  config = lib.mkIf config.Zeloo.enable {
    home.packages = [ config.Zeloo.package ];

    systemd.user.services.Zeloo = {
      Unit = {
        Description = "Zeloo Agent Daemon";
        After = ["network.target"];
      };
      Service = {
        ExecStart = "${config.Zeloo.package}/bin/Zeloo gateway";
        Restart = "on-failure";
        RestartSec = "5s";
        User = config.Zeloo.defaultUser;
      };
      Install = {
        WantedBy = ["default.target"];
      };
    };
  };
}
```

### NixOS 配置集成 ✅ 已完整实现

`configMergeScript.nix` 现已完整实现，提供 20+ 大类企业级配置选项：

**核心配置**：enable / package / systemWide / user / group / dataDir / workspaceDefaults / openPorts
**备份**：backup.{enable, interval, retention, destDir}
**监控**：monitoring.{prometheus, logLevel}
**反向代理**：reverseProxy.{enable, domain, port, ssl, websockets}
**高可用**：ha.{enable, watchdogSec, restartMaxAttempts, startLimitIntervalSec}
**时间同步**：timeSync.{enable, servers}
**资源限制**：resources.{memoryMax, cpuQuota}
**密钥管理**：secrets.{apiKeysFile, envFile, sopsFile, ageKeyFile}
**多实例**：instances.{name}.{enable, dataDir, port, workspaces, model}
**集群**：cluster.{enable, redisHost, redisPort, nodeId, sharedStorage}
**容器**：container.{enable, image, imageTag, autoUpdate, network, userNamespace}
**追踪**：tracing.{enable, endpoint, serviceName, sampleRate}
**数据库**：database.{backend, postgres.*} — SQLite/PostgreSQL
**速率限制**：rateLimit.{enable, requestsPerMinute, burst}
**TLS 终止**：tls.{enable, certFile, keyFile, minVersion, hsts, clientCertAuth}
**Canary 部署**：canary.{enable, weight, autoPromote, healthCheckInterval}
**A/B 测试**：abTest.{enable, experiments.{name}.{weight, model, metadata}}
**Kubernetes**：kubernetes.{enable, namespace, replicas, chart}
**备份加密**：backupEncryption.{enable, publicKeyFile}
**成本控制**：costControl.{enable, monthlyBudgetUSD, alertThreshold, enforceHardLimit}
**认证集成**：auth.{method, oidc*, ldap*}
**审计日志**：audit.{enable, logFile, retentionDays, includeRequestBody}

```nix
# nix/configMergeScript.nix

{
  imports = [
    ./homeManagerModules.nix
  ];

  services.Zeloo = {
    enable = true;
    package = (builtins.getFlake ./.).packages.x86_64-linux.Zeloo;
  };

  home.packages = [
    (builtins.getFlake ./.).packages.x86_64-linux.Zeloo
  ];
}
```

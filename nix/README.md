# Nix 构建配置

声明式的 Zeloo 打包配置，使用 [Nix Flakes](https://nixos.wiki/wiki/Flakes)。

## 用途

- **可复现构建**：`nix build` 在任何 NixOS 系统上产出同样的二进制
- **隔离的开发环境**：`nix develop` 提供与 CI 一致的依赖，无需污染全局 Python 环境
- **CI 集成**：`checks.nix` 定义 `pytest` / `ruff` / `format` 三个完整性检查

## 目录

| 文件 | 作用 |
|---|---|
| `flake.nix` | Flake 入口，定义输入/输出 |
| `Zeloo.nix` | 主包构建表达式（`buildPythonPackage`） |
| `devShell.nix` | 开发 shell（含 venvShellHook） |
| `checks.nix` | CI 完整性检查（pytest / ruff / format） |

## 使用

```bash
# 构建包
nix build

# 进入开发环境
nix develop

# 运行 CI 检查
nix flake check
```

## 在 NixOS 上启用

```nix
{
  inputs.Zeloo.url = "github:Zeloo/Zeloo";
  outputs = { self, Zeloo }: {
    environment.systemPackages = [ Zeloo.packages.x86_64-linux.Zeloo ];
  };
}
```
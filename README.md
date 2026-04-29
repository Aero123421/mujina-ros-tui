# Mujina Assist

Mujina Assist は、公式 `mujina_ros` を安全にセットアップ・診断・運用するための日本語TUIアプリです。

このプロジェクトは公式 `mujina_ros` の置き換えではありません。公式リポジトリを `third_party/mujina_ros` に clean upstream mirror として内包し、実行時には `workspace/src/mujina_ros` へ生成コピーして使います。安全運用のための差分は `patches/mujina_ros` の patch queue と Mujina Assist 側の診断・preflight・wizard で管理します。

## 目的

- 起動直後にTUIを開き、workspace、build、policy、device、CAN、motor、zero、SIM、実機preflightの状態を一覧する
- `third_party/mujina_ros` の固定commitをもとに再現性のある workspace を作る
- `vanilla` と `assisted` のモードを分け、patch適用状態とdirty状態を表示する
- external policy は manifest と SIM verification がない限り実機投入しない
- zero position は post-zero verification と zero profile 保存を前提にする
- 実機起動は安全ゲートを通るまでロックする
- 長い処理や常駐ノードは既存job systemで管理し、ログと復旧状態をTUIから追えるようにする

## 使い方

Ubuntu 24.04 のターミナルで次を実行します。

```bash
git clone <this-repository>
cd <cloned-directory>
./start.sh
```

`./start.sh` は `.venv` を準備し、通常はTUIを起動します。旧番号メニューは互換用に残しています。

```bash
./start.sh legacy-menu
./start.sh menu --legacy
```

開発・自動化・緊急操作用のサブコマンドも残しています。

```bash
./start.sh doctor
./start.sh build
./start.sh sim
./start.sh policy --test
```

## 内包 upstream

現在内包している公式 upstream:

- Repository: `https://github.com/rt-net/mujina_ros`
- Commit: `38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d`
- License: MIT License
- License file: `third_party/mujina_ros/LICENSE`

`third_party/mujina_ros` は clean mirror として扱います。直接編集せず、公式との差分は `patches/mujina_ros/*.patch` として管理してください。詳細は `THIRD_PARTY_NOTICES.md` を参照してください。

## Workspace mode

- `vanilla`: 内包した公式 `mujina_ros` をそのまま `workspace/src/mujina_ros` へコピーする
- `assisted`: コピー後に `patches/mujina_ros` のpatch queueを適用する
- `diagnostic`: 実機にトルクを送る操作を避け、診断中心で扱う

workspace signature は upstream commit、patch set hash、dirty状態を含みます。signature が変わると、既存の SIM verified は無効になります。

## Safety model

Real launch は少なくとも次の条件が揃うまでロックされます。

- workspace がbuild済み
- active policy の provenance が分かる
- external policy に manifest がある
- 現在の policy と workspace signature で SIM verified 済み
- CAN が健全
- IMU が確認できる
- zero profile が verified
- operator checklist と `REAL` confirmation が完了
- manual recovery が未解決ではない

## テスト

このプロジェクト自身のテストは `tests/` に限定しています。`third_party/mujina_ros` のROS/ament系テストは、ROS 2 Jazzy 環境で別途扱います。

```bash
python -m pytest -q
```

コンテナ経由の確認:

```bash
./scripts/run-docker-tests.sh
```

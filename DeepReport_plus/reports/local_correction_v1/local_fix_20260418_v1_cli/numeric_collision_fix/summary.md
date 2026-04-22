# Numeric Collision 修复实验（numeric_collision_fix_v1）

- 修复前数字准确率（numeric_accuracy）: 0.75
- 修复后数字准确率（numeric_accuracy）: 1.0
- 增量（numeric_accuracy_delta）: 0.25

## 修复分解（fix_breakdown）

- 近邻数字碰撞（nearest_number_collision）: 30
- 单位修复（unit_fix）: 30
- 期间修复（period_fix）: 0

## 说明

- 优先覆盖 revenue/yoy 近邻碰撞，并补 unit/period 三类离线修复对比。
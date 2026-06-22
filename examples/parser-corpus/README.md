# Java Parser Corpus / Java Parser 公开语料

This directory contains sanitized Java fixtures for regex/tree-sitter differential evaluation. It does not contain private project code.

本目录包含用于 regex/tree-sitter 差异评测的脱敏 Java fixture，不包含任何私有项目源码。

Coverage / 覆盖范围：

- overloaded methods and nested generics / 方法重载与嵌套泛型
- nested and anonymous classes / 内部类与匿名类
- interface default methods, inheritance and fallback implementations / interface default method、继承与 fallback
- Lombok constructor injection / Lombok 构造器注入
- annotation constants and composed Controller/Feign paths / 注解常量与组合路径
- generic controllers and common `@RequestMapping` methods / 泛型 Controller 与通用 RequestMapping
- switch expressions, lambdas and method references / switch expression、lambda 与 method reference

Run / 运行：

```bash
python -m pytest -q tests/test_parser_differential.py
```

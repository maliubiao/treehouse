module.exports = grammar({
  name: "gptlang",

  rules: {
    // 顶层规则，由多个元素交替组成
    source_file: ($) => repeat($._element),

    // 元素可以是四种类型之一
    _element: ($) =>
      choice($.command, $.block, $.output_declaration, $.text_content),

    // @命令规则
    command: ($) => seq("@", field("name", $.identifier)),

    // 块规则 { ... }
    block: ($) =>
      seq(
        "{",
        repeat(
          choice(
            $._block_content, // 优先级调整
            $.command,
          ),
        ),
        "}",
      ),

    // 块内内容（不允许包含=）
    _block_content: ($) => choice($.block_text, $.command),

    // 块内文本（排除=和{}）
    block_text: ($) => /[^={}@]+/,

    // 输出路径声明
    output_declaration: ($) => seq("=", field("path", $.path)),

    // 路径规则（支持Windows和POSIX）
    path: ($) => /[a-zA-Z0-9_\/\\:\-. ]+/,

    // 普通文本内容（排除特殊符号）
    text_content: ($) => /[^@={}]+/,

    // 标识符规则
    identifier: ($) => /[a-zA-Z_][a-zA-Z0-9_]*/,
  },

  conflicts: ($) => [[$.block, $._block_content]],
});

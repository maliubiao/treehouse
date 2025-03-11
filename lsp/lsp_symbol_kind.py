class SymbolKind:
    File = 1
    Module = 2
    Namespace = 3
    Package = 4
    Class = 5
    Method = 6
    Property = 7
    Field = 8
    Constructor = 9
    Enum = 10
    Interface = 11
    Function = 12
    Variable = 13
    Constant = 14
    String = 15
    Number = 16
    Boolean = 17
    Array = 18
    Object = 19
    Key = 20
    Null = 21
    EnumMember = 22
    Struct = 23
    Event = 24
    Operator = 25
    TypeParameter = 26

    @staticmethod
    def to_string(kind: int) -> str:
        kind_to_string = {
            SymbolKind.File: "File",
            SymbolKind.Module: "Module",
            SymbolKind.Namespace: "Namespace",
            SymbolKind.Package: "Package",
            SymbolKind.Class: "Class",
            SymbolKind.Method: "Method",
            SymbolKind.Property: "Property",
            SymbolKind.Field: "Field",
            SymbolKind.Constructor: "Constructor",
            SymbolKind.Enum: "Enum",
            SymbolKind.Interface: "Interface",
            SymbolKind.Function: "Function",
            SymbolKind.Variable: "Variable",
            SymbolKind.Constant: "Constant",
            SymbolKind.String: "String",
            SymbolKind.Number: "Number",
            SymbolKind.Boolean: "Boolean",
            SymbolKind.Array: "Array",
            SymbolKind.Object: "Object",
            SymbolKind.Key: "Key",
            SymbolKind.Null: "Null",
            SymbolKind.EnumMember: "EnumMember",
            SymbolKind.Struct: "Struct",
            SymbolKind.Event: "Event",
            SymbolKind.Operator: "Operator",
            SymbolKind.TypeParameter: "TypeParameter",
        }
        return kind_to_string.get(kind, "Unknown")


package main

type OuterStruct struct {
    InnerStruct struct {
	Value int
    }
}

func (o OuterStruct) Method1() {}
func (o *OuterStruct.InnerStruct) Method2() {}

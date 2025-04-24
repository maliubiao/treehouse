//go:build example
// +build example

/*
Package main 用于测试tree-sitter的Go语法解析能力
包含Go语言各种典型语法结构

测试命令注释示例:
//go:generate stringer -type=Status -output=status_string.go
//go:noinline
//lint:ignore U1000 测试忽略未使用检查
*/
package main

import "fmt"

import (
	"context"
	"errors"
	_ "io"
	math "math"
	sync "sync"
)

//go:generate echo "Generating code..."

// 全局常量声明
const (
	MAX_SIZE = 1 << 10
	MIN_SIZE = 1 << 2
	StatusPending = iota    // 待处理状态
	StatusProcessing        // 处理中状态
	StatusCompleted         // 已完成状态
)

// 全局变量声明
var (
	instance     *Singleton
	instanceOnce sync.Once
	_ Geometry = (*Circle)(nil) // 接口实现检查
)

// 自定义类型定义
type (
	// 坐标结构体
	Point struct {
		X, Y float64 `json:"x"` // 坐标字段
		Desc string  `json:"desc" xml:"description"`
		ctx  context.Context    // 上下文（测试嵌套注释/*示例*/）
	}

	// 几何接口
	Geometry interface {
		Area() float64      // 计算面积
		Perimeter() float64 // 计算周长
	}

	// 类型别名
	PointList []*Point

	// 自定义错误类型
	MyError struct {
		Msg string // 错误信息
	}

	// 圆形结构体（内嵌Point）
	Circle struct {
		Point         // 内嵌点坐标
		Radius float64 // 半径 /* 测试块注释 */
	}
)

// 错误接口实现
func (e *MyError) Error() string {
	return e.Msg
}

// NewPoint 构造函数
// 参数x,y为坐标值，返回四舍五入后的Point指针
// 自动初始化context.Background()
func NewPoint(x, y float64) *Point {
	return &Point{
		X:   math.Round(x),
		Y:   math.Round(y),
		ctx: context.Background(),
	}
}

// 结构体方法（值接收者）
// 计算到原点的欧式距离
func (p Point) DistanceToOrigin() float64 {
	return math.Sqrt(p.X*p.X + p.Y*p.Y)
}

// 结构体方法（指针接收者）
// 按比例缩放坐标
func (p *Point) Scale(factor float64) {
	p.X *= factor
	p.Y *= factor
}

// 实现Geometry接口
func (p *Point) Area() float64 {
	return 0
}

func (p *Point) Perimeter() float64 {
	return p.DistanceToOrigin() * 2
}

// 圆形结构体方法
// 计算圆面积（覆盖Point实现）
func (c *Circle) Area() float64 {
	return math.Pi * c.Radius * c.Radius
}

// 复杂函数示例
// 处理点集合并返回处理计数
// 使用context进行超时控制
func ProcessPoints(ctx context.Context, points ...*Point) (count int, err error) {
	if len(points) == 0 {
		return 0, errors.New("empty points")
	}

LOOP:
	for i, p := range points {
		select {
		case <-ctx.Done():
			break LOOP
		default:
			p.Scale(1.1)
			count += i
		}
	}

	return count, nil
}

// GenericAdd 泛型加法函数
// 支持int和float64类型参数
// 返回两数之和（类型与参数一致）
func GenericAdd[T int | float64](a, b T) T {
	return a + b
}

// MayFail 条件错误生成函数
// 当flag为true时返回自定义错误
// 用于测试错误处理流程
func MayFail(flag bool) error {
	if flag {
		return &MyError{"something went wrong"}
	}
	return nil
}

// MethodExpressionExample 方法表达式示例
// 展示如何将方法作为函数值调用
func MethodExpressionExample() {
	p := NewPoint(1, 2)
	scaleFunc := (*Point).Scale
	scaleFunc(p, 2.0)
}

// Factorial 递归阶乘计算
// 输入n<=0时返回1
func Factorial(n int) int {
	if n <= 0 {
		return 1
	}
	return n * Factorial(n-1)
}

// LabeledLoopExample 带标签循环示例
// 展示如何中断外层循环
func LabeledLoopExample() {
outer:
	for i := 0; i < 5; i++ {
		for j := 0; j < 5; j++ {
			if i*j > 10 {
				break outer
			}
			fmt.Println(i, j)
		}
	}
}

// DeferPanicRecoverExample 异常处理示例
// 展示panic/recover工作机制
func DeferPanicRecoverExample() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Println("Recovered from panic:", r)
		}
	}()
	panic("something bad happened")
}

// ChannelRangeExample 通道遍历示例
// 展示如何消费缓冲通道
func ChannelRangeExample() {
	ch := make(chan int, 3)
	ch <- 1
	ch <- 2
	ch <- 3
	close(ch)
	for v := range ch {
		fmt.Println(v)
	}
}

// TypeSwitchExample 类型断言示例
// 根据几何类型执行不同操作
func TypeSwitchExample(g Geometry) {
	switch v := g.(type) {
	case *Point:
		fmt.Println("Point with area:", v.Area())
	case *Circle:
		fmt.Println("Circle with radius:", v.Radius)
	default:
		fmt.Println("Unknown geometry")
	}
}

// Adder 高阶函数示例
// 返回闭包函数实现累加
func Adder(a int) func(int) int {
	return func(b int) int {
		return a + b
	}
}

// 单例模式实现
func GetInstance() *Singleton {
	instanceOnce.Do(func() {
		instance = &Singleton{
			mu:    new(sync.Mutex),
			cache: make(map[string]interface{}),
		}
	})
	return instance
}

type Singleton struct {
	mu    *sync.Mutex
	cache map[string]interface{}
}

// Get 从缓存获取值
// 返回值和存在状态（测试命名返回值）
func (s *Singleton) Get(key string) (value interface{}, ok bool) {
	s.mu.Lock()
	defer s.mu.Unlock()

	value, ok = s.cache[key]
	return
}

// init函数示例
func init() {
	fmt.Println("Package initialized")
}

// 主函数
func main() {
	// 变量短声明
	points := PointList{
		NewPoint(1.1, 2.2),
		{X: 3.3, Y: 4.4},
	}

	// 函数调用
	if _, err := ProcessPoints(context.TODO(), points...); err != nil {
		Printf("处理错误: %v\n", err)
	}

	// 类型转换
	var i interface{} = "hello"
	if s, ok := i.(string); ok {
		Println("字符串长度:", len(s))
	}

	// 通道使用
	ch := make(chan int, 1)
	ch <- 42
	select {
	case v := <-ch:
		Println("收到值:", v)
	default:
		Println("默认")
	}

	// 调用新增函数示例
	DeferPanicRecoverExample()
	LabeledLoopExample()
	fmt.Println(GenericAdd(1, 2))
	fmt.Println(GenericAdd(3.14, 2.718))
}

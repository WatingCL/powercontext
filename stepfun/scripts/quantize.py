/**
 * 把 fp32 ONNX 权重转成 INT8（动态量化）与 FP16。
 * 仓库里直接下载的三档权重由同一套流程产生，本脚本用于从零复现。
 *
 * 依赖：pip install onnx onnxruntime onnxconverter-common
 * 用法：python scripts/quantize.py
 */
import os
from pathlib import Path

SRC = Path("public/models/bge-small-zh-v1.5/onnx/model.onnx")
OUT_INT8 = SRC.with_name("model_int8_regen.onnx")
OUT_FP16 = SRC.with_name("model_fp16_regen.onnx")


def quantize_int8():
    from onnxruntime.quantization import quantize_dynamic, QuantType

    quantize_dynamic(
        model_input=str(SRC),
        model_output=str(OUT_INT8),
        weight_type=QuantType.QInt8,
        per_channel=False,
        reduce_range=False,
    )
    print(f"INT8 -> {OUT_INT8}  {OUT_INT8.stat().st_size / 1048576:.1f}MB")


def convert_fp16():
    import onnx
    from onnxconverter_common import float16

    model = onnx.load(str(SRC))
    model_fp16 = float16.convert_float_to_float16(model, keep_io_types=True)
    onnx.save(model_fp16, str(OUT_FP16))
    print(f"FP16 -> {OUT_FP16}  {OUT_FP16.stat().st_size / 1048576:.1f}MB")


if __name__ == "__main__":
    if not SRC.exists():
        raise SystemExit(f"找不到 {SRC}，请先运行 npm run setup:model")
    base = os.path.getsize(SRC) / 1048576
    quantize_int8()
    convert_fp16()
    print(f"fp32 基线 {base:.1f}MB")
    print(f"压缩比 fp32/int8 = {base / (os.path.getsize(OUT_INT8) / 1048576):.2f}x")
    print(f"压缩比 fp32/fp16 = {base / (os.path.getsize(OUT_FP16) / 1048576):.2f}x")
    print("注：仓库自带的三档权重为官方发布版本，与本脚本同一量化配方；本脚本产出带 _regen 后缀，便于对照。")

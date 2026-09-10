---
license: mit
pretty_name: U-MATH
task_categories:
- text-generation
language:
- en
tags:
- math
- reasoning
size_categories:
- 1K<n<10K
dataset_info:
  features:
  - name: uuid
    dtype: string
  - name: subject
    dtype: string
  - name: has_image
    dtype: bool
  - name: image
    dtype: string
  - name: problem_statement
    dtype: string
  - name: golden_answer
    dtype: string
  splits:
  - name: test
    num_examples: 1100
configs:
- config_name: default
  data_files:
  - split: test
    path: data/test-*
---

**U-MATH** is a comprehensive benchmark of 1,100 unpublished university-level problems sourced from real teaching materials. 

It is designed to evaluate the mathematical reasoning capabilities of Large Language Models (LLMs). \
The dataset is balanced across six core mathematical topics and includes 20% of multimodal problems (involving visual elements such as graphs and diagrams). 

For fine-grained performance evaluation results and detailed discussion, check out our [paper](LINK).

* 📊 [U-MATH benchmark at Huggingface](https://huggingface.co/datasets/toloka/umath)
* 🔎 [μ-MATH benchmark at Huggingface](https://huggingface.co/datasets/toloka/mumath)
* 🗞️ [Paper](https://arxiv.org/abs/2412.03205)
* 👾 [Evaluation Code at GitHub](https://github.com/Toloka/u-math/)

### Key Features
* **Topics Covered**: Precalculus, Algebra, Differential Calculus, Integral Calculus, Multivariable Calculus, Sequences & Series.
* **Problem Format**: Free-form answer with LLM judgement
* **Evaluation Metrics**: Accuracy; splits by subject and text-only vs multimodal problem type.
* **Curation**: Original problems composed by math professors and used in university curricula, samples validated by math experts at [Toloka AI](https://toloka.ai), [Gradarius](https://www.gradarius.com)

### Use it

```python
from datasets import load_dataset
ds = load_dataset('toloka/u-math', split='test')
```

### Dataset Fields
`uuid`: problem id \
`has_image`: a boolean flag on whether the problem is multimodal or not \
`image`: binary data encoding the accompanying image, empty for text-only problems \
`subject`: subject tag marking the topic that the problem belongs to \
`problem_statement`: problem formulation, written in natural language \
`golden_answer`: a correct solution for the problem, written in natural language \

For meta-evaluation (evaluating the quality of LLM judges), refer to the [µ-MATH dataset](https://huggingface.co/datasets/toloka/mu-math).

### Evaluation Results

<div align="center">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/6338929107f5708a1aca1390/oM5T6XAYTh1eR3UQA4bmj.png" alt="umath-table" width="800"/>
</div>

<div align="center">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/6338929107f5708a1aca1390/eG2Ydegz5xj6cYCrH_f8E.png" alt="umath-bar" width="800"/>
</div>

The prompt used for inference:

```
{problem_statement}
Please reason step by step, and put your final answer within \boxed{}
```

### Licensing Information
All the dataset contents are available under the MIT license.

### Citation
If you use U-MATH or μ-MATH in your research, please cite the paper:
```bibtex
@inproceedings{umath2024,
title={U-MATH: A University-Level Benchmark for Evaluating Mathematical Skills in LLMs},
author={Konstantin Chernyshev, Vitaliy Polshkov, Ekaterina Artemova, Alex Myasnikov, Vlad Stepanov, Alexei Miasnikov and Sergei Tilga},
year={2024}
}
```

### Contact
For inquiries, please contact kchernyshev@toloka.ai
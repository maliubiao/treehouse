# Transcript Cleanup Prompt

## Task Description
Process spoken language transcripts to:
1. Remove filler words (e.g., 嗯, 啊, 这个, 那个, 就是)
2. Eliminate repetitive phrases
3. Fix speech pauses indicated by punctuation
4. Maintain original meaning and factual content
5. Preserve professional terminology and names

## Processing Steps
1. **Identify and Remove**:
   - Verbal fillers: 呃, 嘛, 啦, 呀, 哦
   - Hesitation markers: "那个...", "就是..."
   - Repeated phrases within 3 words
   - Empty rhetorical questions

2. **Structural Cleanup**:
   - Merge broken sentences
   - Fix comma splices
   - Normalize punctuation
   - Remove self-corrections (e.g., "不是-我的意思是")

3. **Context Preservation**:
   - Keep technical terms unchanged
   - Maintain original speaker intent
   - Preserve numerical data and dates
   - Retain rhetorical devices when intentional

## Examples

Input: 
"嗯，这个我们今天要讨论的是，呃，区块链技术的应用，啊对，在供应链管理中的实际应用案例。"

Output:
"我们今天要讨论的是区块链技术在供应链管理中的实际应用案例。"

---

Input:
"然后就是... 那个... 物流追踪系统需要，需要确保数据的不可篡改性，对吧？也就是说，一旦录入就不能修改。"

Output:
"物流追踪系统需要确保数据的不可篡改性。一旦录入就不能修改。"

---

Input:
"这个方案可能... 我的意思是，或许需要考虑边缘计算节点，配合5G网络，对吧？"

Output:
"这个方案需要考虑边缘计算节点配合5G网络。"

## Special Instructions
- Keep regional accents intact
- Maintain industry-specific jargon
- Retain meaningful stutters for emphasis
- Flag uncertain interpretations with [?]
- Output in simplified Chinese
- Avoid formal rewriting
- Preserve original paragraph structure

const fs = require('fs');
const path = 'd:/Desktop/QuantAgent/frontend/my-app/app/replay/page.tsx';
const content = fs.readFileSync(path, 'utf8');

const lines = content.split('\n');
console.log('Original line count:', lines.length);

// 分析文件结构
let fixed = [];
let buffer = '';

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  const trimmedLine = line.trim();
  
  // 空行处理
  if (trimmedLine === '') {
    if (buffer) {
      fixed.push(buffer);
      buffer = '';
    }
    fixed.push('');
    continue;
  }
  
  // 合并到buffer
  buffer = buffer ? buffer + line : line;
  
  // 检查是否应该结束当前行
  const lastChar = buffer.trim().slice(-1);
  const goodEnding = [';', ',', '{', '}', '[', ']', '(', ')', '`', '"', "'"].includes(lastChar) || buffer.endsWith('*/');
  
  const nextLine = lines[i + 1] || '';
  const nextTrimmed = nextLine.trim();
  
  // 下一行是新语句开始的模式
  const newStatementPatterns = [
    /^import /, /^export /, /^const /, /^let /, /^var /, /^function /,
    /^interface /, /^type /, /^\/\/ /, /^\/\*/, /^\* /, /^return /,
    /^if \(/, /^else /, /^for /, /^while /, /^switch /, /^case /,
    /^default:/, /^try /, /^catch /, /^finally /, /^throw /, /^async /,
    /^await /, /^class /, /^<[A-Z]/, /^<\/[A-Z]/, /^function\(/,
    /^\w+\.\w+\(/, /^}\s*$/
  ];
  
  const nextIsNewStatement = newStatementPatterns.some(p => p.test(nextTrimmed));
  const nextIsEmpty = nextTrimmed === '';
  
  // 如果buffer以好的结束符结束，或者下一行是空行/新语句，则结束当前行
  if (goodEnding || nextIsEmpty || nextIsNewStatement) {
    fixed.push(buffer);
    buffer = '';
  }
}

if (buffer) fixed.push(buffer);

console.log('Fixed line count:', fixed.length);

// 写入修复后的文件
fs.writeFileSync(path, fixed.join('\n'), 'utf8');
console.log('File saved successfully!');

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, relative, sep } from 'node:path';

const projectRoot = process.cwd();
const articlesRoot = join(projectRoot, 'src', 'content', 'articles');
const sourcesRoot = join(projectRoot, 'src', 'content', 'sources');
const implementationFence = /^```(?:python|py|c|cpp|c\+\+|arduino|ino|typescript|ts|javascript|js|yaml|yml|json|xml)\s*$/m;
const forbiddenSegments = new Set([
	'.cache',
	'.venv',
	'__pycache__',
	'build',
	'install',
	'log',
	'node_modules',
]);
const textExtensions = new Set([
	'.cfg',
	'.cpp',
	'.h',
	'.ino',
	'.js',
	'.json',
	'.md',
	'.py',
	'.sh',
	'.txt',
	'.xml',
	'.yaml',
	'.yml',
]);

/*
 * @description         : 递归列出目录中的全部文件
 * @param directory     : 要扫描的绝对目录
 * @return              : 绝对文件路径数组
 */
function listFiles(directory) {
	return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
		const path = join(directory, entry.name);
		return entry.isDirectory() ? listFiles(path) : [path];
	});
}

/*
 * @description         : 从Markdown frontmatter读取sourceDir
 * @param content       : 完整Markdown文本
 * @return              : sourceDir字符串，未声明时返回空字符串
 */
function readSourceDir(content) {
	const frontmatter = content.match(/^---\s*\n([\s\S]*?)\n---/);
	if (!frontmatter) return '';
	return frontmatter[1].match(/^sourceDir:\s*["']?([a-z0-9][a-z0-9-]*)["']?\s*$/m)?.[1] ?? '';
}

/*
 * @description         : 检查源码目录是否包含秘密或生成产物
 * @param sourceDir     : 文章声明的源码目录名
 * @return              : 发现问题时返回错误文本数组
 */
function validateSourceDirectory(sourceDir) {
	const errors = [];
	const directory = join(sourcesRoot, sourceDir);
	if (!existsSync(directory) || !statSync(directory).isDirectory()) {
		return [`sourceDir ${sourceDir} 对应目录不存在`];
	}

	const files = listFiles(directory);
	if (files.length === 0) return [`sourceDir ${sourceDir} 中没有源码文件`];

	for (const file of files) {
		const sourcePath = relative(directory, file);
		const segments = sourcePath.split(sep);
		if (segments.some((segment) => forbiddenSegments.has(segment))) {
			errors.push(`${sourceDir}/${sourcePath} 是缓存或构建产物`);
		}
		if (sourcePath.endsWith('.pyc') || sourcePath.endsWith('.log') || segments.includes('.gateway-token')) {
			errors.push(`${sourceDir}/${sourcePath} 不应发布`);
		}
		if (!textExtensions.has(extname(file).toLowerCase())) continue;

		const content = readFileSync(file, 'utf8');
		if (/BEGIN [A-Z ]*PRIVATE KEY|ssh-ed25519\s+AAAA/i.test(content)) {
			errors.push(`${sourceDir}/${sourcePath} 包含私钥或SSH公钥材料`);
		}
		for (const line of content.split(/\r?\n/)) {
			if (line.includes('ZDT_CAN_GATEWAY_TOKEN:') && !line.includes('<随机令牌>')) {
				errors.push(`${sourceDir}/${sourcePath} 包含未脱敏的CAN网关令牌`);
			}
		}
	}
	return errors;
}

const errors = [];
for (const articleName of readdirSync(articlesRoot).filter((name) => name.endsWith('.md') || name.endsWith('.mdx'))) {
	const articlePath = join(articlesRoot, articleName);
	const content = readFileSync(articlePath, 'utf8');
	const sourceDir = readSourceDir(content);

	if (implementationFence.test(content) && !sourceDir) {
		errors.push(`${articleName} 展示了实现代码，但没有声明sourceDir`);
		continue;
	}
	if (sourceDir) {
		errors.push(...validateSourceDirectory(sourceDir).map((error) => `${articleName}: ${error}`));
	}
}

if (errors.length > 0) {
	console.error('文章与源码检查失败：');
	for (const error of errors) console.error(`- ${error}`);
	process.exit(1);
}

console.log('文章与配套源码检查通过。');

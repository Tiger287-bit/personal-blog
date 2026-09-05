export interface ArticleSourceFile {
	path: string;
	name: string;
	group: string;
	language: string;
	highlighterLanguage: string;
	content: string;
	lineCount: number;
	previewable: boolean;
	downloadUrl: string;
}

export type ArticleSourceLink = Omit<ArticleSourceFile, 'content'>;

export interface ArticleSourceTreeRow {
	kind: 'directory' | 'file';
	name: string;
	path: string;
	depth: number;
	file?: ArticleSourceLink;
}

interface MutableSourceDirectory {
	kind: 'directory';
	name: string;
	path: string;
	children: MutableSourceNode[];
}

interface MutableSourceFile {
	kind: 'file';
	name: string;
	path: string;
	file: ArticleSourceLink;
}

type MutableSourceNode = MutableSourceDirectory | MutableSourceFile;

const sourceTextModules = import.meta.glob<string>([
	'./content/sources/**/*.{c,cfg,cpp,h,ino,js,json,md,properties,py,sh,txt,xml,yaml,yml}',
	'./content/sources/**/.gitignore',
	'./content/sources/**/LICENSE',
	'./content/sources/**/Doxyfile',
	'./content/sources/**/resource/*',
], {
	query: '?raw',
	import: 'default',
	eager: true,
	exhaustive: true,
});

const sourceAssetModules = import.meta.glob<string>([
	'./content/sources/**/*',
	'./content/sources/**/.gitignore',
], {
	query: '?url',
	import: 'default',
	eager: true,
	exhaustive: true,
});

const languageByExtension: Record<string, string> = {
	c: 'C',
	cfg: 'Config',
	cpp: 'C++',
	h: 'C++ Header',
	ino: 'Arduino',
	js: 'JavaScript',
	json: 'JSON',
	md: 'Markdown',
	properties: 'Properties',
	py: 'Python',
	sh: 'Shell',
	txt: 'Text',
	xml: 'XML',
	yaml: 'YAML',
	yml: 'YAML',
	gitignore: 'Git Ignore',
	whl: 'Python Wheel',
};

const highlighterLanguageByExtension: Record<string, string> = {
	c: 'c',
	cfg: 'ini',
	cpp: 'cpp',
	h: 'cpp',
	ino: 'cpp',
	js: 'javascript',
	json: 'json',
	md: 'markdown',
	properties: 'ini',
	py: 'python',
	sh: 'bash',
	txt: 'text',
	xml: 'xml',
	yaml: 'yaml',
	yml: 'yaml',
	gitignore: 'text',
};

/*
 * @description         : 根据扩展名和可读状态返回源码阅读页显示的文件类型
 * @param path          : 源码文件相对路径
 * @param previewable   : 是否可以作为文本读取
 * @return              : 文本语言或二进制文件类型名称
 */
function getLanguage(path: string, previewable: boolean): string {
	const extension = path.split('.').pop()?.toLowerCase() ?? '';
	return languageByExtension[extension] ?? (previewable ? 'Text' : 'Binary');
}

/*
 * @description         : 根据源码文件扩展名返回Shiki使用的语言ID
 * @param path          : 源码文件相对路径
 * @return              : Shiki语言ID，未知扩展名返回text
 */
function getHighlighterLanguage(path: string): string {
	const extension = path.split('.').pop()?.toLowerCase() ?? '';
	return highlighterLanguageByExtension[extension] ?? 'text';
}

/*
 * @description         : 收集指定文章源码目录中的全部文件并标记是否可以预览
 * @param sourceDir     : src/content/sources下的文章源码目录名
 * @return              : 包含文本内容或二进制下载地址的文件列表
 */
export function getArticleSourceFiles(sourceDir?: string): ArticleSourceFile[] {
	if (!sourceDir) return [];

	const prefix = `./content/sources/${sourceDir}/`;
	return Object.entries(sourceAssetModules)
		.filter(([modulePath]) => modulePath.startsWith(prefix))
		.map(([modulePath, downloadUrl]) => {
			const path = modulePath.slice(prefix.length);
			const segments = path.split('/');
			const sourceText = sourceTextModules[modulePath];
			const previewable = typeof sourceText === 'string';
			const normalizedContent = previewable ? sourceText.replace(/\r\n/g, '\n') : '';
			const lineCount = normalizedContent === ''
				? 0
				: normalizedContent.split('\n').length - (normalizedContent.endsWith('\n') ? 1 : 0);

			return {
				path,
				name: segments.at(-1) ?? path,
				group: segments.length > 1 ? segments[0] : 'root',
				language: getLanguage(path, previewable),
				highlighterLanguage: getHighlighterLanguage(path),
				content: normalizedContent,
				lineCount,
				previewable,
				downloadUrl,
			};
		})
		.sort((left, right) => left.path.localeCompare(right.path, 'en'));
}

/*
 * @description         : 将平面源码文件列表转换为文件夹优先的目录树行
 * @param files         : 当前文章的源码文件列表
 * @return              : 包含节点类型、深度和完整路径的目录树行
 */
export function getArticleSourceTree(files: ArticleSourceLink[]): ArticleSourceTreeRow[] {
	const root: MutableSourceDirectory = {
		kind: 'directory',
		name: '',
		path: '',
		children: [],
	};

	for (const file of files) {
		const segments = file.path.split('/');
		let directory = root;
		for (let index = 0; index < segments.length - 1; index += 1) {
			const name = segments[index];
			const path = segments.slice(0, index + 1).join('/');
			let child = directory.children.find(
				(node): node is MutableSourceDirectory => node.kind === 'directory' && node.name === name,
			);
			if (!child) {
				child = { kind: 'directory', name, path, children: [] };
				directory.children.push(child);
			}
			directory = child;
		}
		directory.children.push({
			kind: 'file',
			name: segments.at(-1) ?? file.name,
			path: file.path,
			file,
		});
	}

	/*
	 * @description         : 按文件夹优先、名称升序整理每一级目录
	 * @param directory     : 当前可变目录节点
	 * @return              : 无返回值
	 */
	const sortDirectory = (directory: MutableSourceDirectory): void => {
		directory.children.sort((left, right) => {
			if (left.kind !== right.kind) return left.kind === 'directory' ? -1 : 1;
			return left.name.localeCompare(right.name, 'en');
		});
		for (const child of directory.children) {
			if (child.kind === 'directory') sortDirectory(child);
		}
	};
	sortDirectory(root);

	const rows: ArticleSourceTreeRow[] = [];
	/*
	 * @description         : 深度优先展开目录树供Astro模板逐行渲染
	 * @param directory     : 当前目录节点
	 * @param depth         : 当前目录子节点的缩进深度
	 * @return              : 无返回值
	 */
	const flattenDirectory = (directory: MutableSourceDirectory, depth: number): void => {
		for (const child of directory.children) {
			rows.push({
				kind: child.kind,
				name: child.name,
				path: child.path,
				depth,
				file: child.kind === 'file' ? child.file : undefined,
			});
			if (child.kind === 'directory') flattenDirectory(child, depth + 1);
		}
	};
	flattenDirectory(root, 0);
	return rows;
}

/*
 * @description         : 为文章或源码文件生成站内链接
 * @param section       : 文章所属板块ID
 * @param articleSlug   : 文章slug
 * @param sourcePath    : 可选的源码相对路径
 * @return              : 文章正文或源码阅读页链接
 */
export function getArticleSourceHref(
	section: string,
	articleSlug: string,
	sourcePath?: string,
): string {
	const articleBase = section === 'app-lab' ? `/app-lab/${articleSlug}` : `/blog/${articleSlug}`;
	if (!sourcePath) return `${articleBase}/`;

	const encodedPath = sourcePath
		.split('/')
		.map((segment) => encodeURIComponent(segment))
		.join('/');
	return `${articleBase}/source/${encodedPath}/`;
}

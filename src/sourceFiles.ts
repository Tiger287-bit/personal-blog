export interface ArticleSourceFile {
	path: string;
	name: string;
	group: string;
	language: string;
	content: string;
	lineCount: number;
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

const sourceModules = import.meta.glob<string>('./content/sources/**/*', {
	query: '?raw',
	import: 'default',
	eager: true,
});

const languageByExtension: Record<string, string> = {
	cpp: 'C++',
	h: 'C++ Header',
	ino: 'Arduino',
	js: 'JavaScript',
	json: 'JSON',
	md: 'Markdown',
	py: 'Python',
	sh: 'Shell',
	txt: 'Text',
	xml: 'XML',
	yaml: 'YAML',
	yml: 'YAML',
};

/*
 * @description         : 根据扩展名返回源码阅读页显示的语言名称
 * @param path          : 源码文件相对路径
 * @return              : 语言名称，未知扩展名返回Text
 */
function getLanguage(path: string): string {
	const extension = path.split('.').pop()?.toLowerCase() ?? '';
	return languageByExtension[extension] ?? 'Text';
}

/*
 * @description         : 读取指定文章源码目录中的全部文本文件
 * @param sourceDir     : src/content/sources下的文章源码目录名
 * @return              : 按相对路径排序的源码文件列表
 */
export function getArticleSourceFiles(sourceDir?: string): ArticleSourceFile[] {
	if (!sourceDir) return [];

	const prefix = `./content/sources/${sourceDir}/`;
	return Object.entries(sourceModules)
		.filter(([modulePath]) => modulePath.startsWith(prefix))
		.map(([modulePath, content]) => {
			const path = modulePath.slice(prefix.length);
			const segments = path.split('/');
			const normalizedContent = content.replace(/\r\n/g, '\n');

			return {
				path,
				name: segments.at(-1) ?? path,
				group: segments.length > 1 ? segments[0] : 'root',
				language: getLanguage(path),
				content: normalizedContent,
				lineCount: normalizedContent === '' ? 0 : normalizedContent.split('\n').length,
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

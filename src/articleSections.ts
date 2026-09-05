export type ArticleSectionTone = 'lab' | 'brick' | 'ros' | 'hardware' | 'general';

export interface ArticleSectionDefinition {
	title: string;
	label: string;
	description: string;
	tone: ArticleSectionTone;
	order: number;
}

export const ARTICLE_SECTIONS: Record<string, ArticleSectionDefinition> = {
	'app-lab': {
		title: 'App Lab',
		label: 'ARDUINO · VENTUNO Q',
		description: '用独立小 App 验证硬件、协议和 ROS 2 接口，每篇文章只解决一项能力。',
		tone: 'lab',
		order: 10,
	},
	bricks: {
		title: 'Custom Bricks',
		label: 'REUSABLE · COMPONENTS',
		description: '沉淀可复用的 App Lab 组件：每篇教程说明组件边界、公开 API、依赖、使用方法与完整源码。',
		tone: 'brick',
		order: 15,
	},
	'ros2-app': {
		title: 'ROS 2 与 App 通讯',
		label: 'ROS 2 · APP LAB',
		description: '从 LED、电机和 IMU 示例理解 ROS 2、Arduino App、Custom Brick、RouterBridge 与硬件之间的完整数据链路。',
		tone: 'ros',
		order: 18,
	},
	'embedded-hardware': {
		title: '嵌入式与硬件',
		label: 'HARDWARE · EMBEDDED',
		description: '传感器、接线、驱动与硬件问题的可复现教程。',
		tone: 'hardware',
		order: 20,
	},
	'site-notices': {
		title: '博客公告',
		label: 'SITE · NOTES',
		description: '关于站点功能、内容结构和使用方式的说明。',
		tone: 'general',
		order: 90,
	},
};

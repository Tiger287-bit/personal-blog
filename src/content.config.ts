import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const articles = defineCollection({
	loader: glob({ base: './src/content/articles', pattern: '**/*.{md,mdx}' }),
	schema: ({ image }) =>
		z.object({
			title: z.string(),
			description: z.string(),
			section: z.string().min(1),
			pubDate: z.coerce.date(),
			updatedDate: z.coerce.date().optional(),
			heroImage: z.optional(image()),
			appId: z.string().optional(),
			order: z.number().int().positive().optional(),
			status: z.enum(['planned', 'in-progress', 'verified']).optional(),
			verifiedDate: z.coerce.date().optional(),
			environment: z.array(z.string()).default([]),
			capabilities: z.array(z.string()).default([]),
			sourceDir: z.string().regex(/^[a-z0-9][a-z0-9-]*$/).optional(),
		}),
});

export const collections = { articles };

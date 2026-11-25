CREATE TABLE `rate_limits` (
	`key` text PRIMARY KEY NOT NULL,
	`count` integer NOT NULL,
	`expires` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `rate_expiry` ON `rate_limits` (`expires`);--> statement-breakpoint
CREATE TABLE `reports` (
	`id` text PRIMARY KEY NOT NULL,
	`question_id` text NOT NULL,
	`answer` text NOT NULL,
	`note` text NOT NULL,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `runs` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`day` text NOT NULL,
	`mode` text NOT NULL,
	`daily_key` text,
	`question_ids` text NOT NULL,
	`answers` text DEFAULT '[]' NOT NULL,
	`round` integer DEFAULT 0 NOT NULL,
	`phase` text DEFAULT 'question' NOT NULL,
	`deadline` integer NOT NULL,
	`score` integer DEFAULT 0 NOT NULL,
	`created_at` integer NOT NULL,
	`finished_at` integer,
	`name` text,
	`published` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `runs_daily_unique` ON `runs` (`daily_key`);--> statement-breakpoint
CREATE INDEX `runs_board` ON `runs` (`day`,`published`,`score`);--> statement-breakpoint
CREATE INDEX `runs_owner` ON `runs` (`owner`,`created_at`);
import { describe, expect, it } from 'vitest';
import {
    getAllCommands,
    navigationItems,
    rankCommandItems,
} from './command-data';

function labelsFor(query: string, isSuperuser = false): string[] {
    return rankCommandItems(getAllCommands(isSuperuser), query).map(item => item.label);
}

function navLabelsFor(query: string): string[] {
    return rankCommandItems(navigationItems, query).map(item => item.label);
}

describe('command palette command matching', () => {
    it.each(['autonomous', 'mission', 'agent run'])('finds Autonomous for %s', query => {
        expect(navLabelsFor(query)).toContain('Autonomous');
    });

    it.each(['test data', 'dataset', 'fixture'])('finds Test Data for %s', query => {
        expect(navLabelsFor(query)[0]).toBe('Test Data');
    });

    it('finds admin Step Registry only when admin commands are included', () => {
        expect(labelsFor('step registry')).not.toContain('Step Registry');
        expect(labelsFor('workflow step')).not.toContain('Step Registry');

        expect(labelsFor('step registry', true)[0]).toBe('Step Registry');
        expect(labelsFor('workflow step', true)[0]).toBe('Step Registry');
    });

    it.each([
        ['ci cd', 'CI/CD'],
        ['ci/cd', 'CI/CD'],
        ['quality gate', 'CI/CD'],
        ['open api', 'Import OpenAPI Spec'],
        ['api-testing', 'API Testing'],
    ])('normalizes %s to match %s', (query, expectedLabel) => {
        expect(labelsFor(query, true)[0]).toBe(expectedLabel);
    });

    it('keeps Discovery searchable outside the sidebar', () => {
        expect(navLabelsFor('discovery session')[0]).toBe('Discovery');
    });

    it('ranks exact word matches above loose substring matches', () => {
        const labels = navLabelsFor('data');

        expect(labels.indexOf('Test Data')).toBeGreaterThanOrEqual(0);
        expect(labels.indexOf('Database Testing')).toBeGreaterThanOrEqual(0);
        expect(labels.indexOf('Test Data')).toBeLessThan(labels.indexOf('Database Testing'));
    });
});

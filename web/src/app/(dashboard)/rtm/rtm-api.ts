export function projectQuery(projectId?: string) {
    return projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
}

export function rtmGenerateJobStatusUrl(apiBase: string, jobId: string, projectId?: string) {
    return `${apiBase}/rtm/generate-jobs/${encodeURIComponent(jobId)}${projectQuery(projectId)}`;
}

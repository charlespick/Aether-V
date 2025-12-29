// Copyright (c) Aether-V
// SPDX-License-Identifier: MPL-2.0

package client

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"golang.org/x/oauth2"
	"golang.org/x/oauth2/clientcredentials"
)

const (
	// Default timeout for API requests
	DefaultTimeout = 30 * time.Second

	// Job polling configuration
	JobPollInterval    = 2 * time.Second
	JobPollMaxAttempts = 150 // 5 minutes max wait
)

// Client is the Aether-V API client.
type Client struct {
	serverURL  string
	httpClient *http.Client
}

// JobStatus represents the status of an async job.
type JobStatus string

const (
	JobStatusPending   JobStatus = "pending"
	JobStatusRunning   JobStatus = "running"
	JobStatusCompleted JobStatus = "completed"
	JobStatusFailed    JobStatus = "failed"
)

// JobResult represents the response from creating an async operation.
type JobResult struct {
	JobID   string `json:"job_id"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

// Job represents a job from the job queue.
type Job struct {
	JobID       string     `json:"job_id"`
	JobType     string     `json:"job_type"`
	Status      JobStatus  `json:"status"`
	CreatedAt   time.Time  `json:"created_at"`
	CompletedAt *time.Time `json:"completed_at,omitempty"`
	TargetHost  *string    `json:"target_host,omitempty"`
	Error       *string    `json:"error,omitempty"`
	Result      any        `json:"result,omitempty"`
}

// NewClient creates a new Aether-V API client with OAuth2 authentication.
func NewClient(ctx context.Context, serverURL, clientID, clientSecret, tenantID string) (*Client, error) {
	// Ensure server URL doesn't have trailing slash
	serverURL = strings.TrimRight(serverURL, "/")

	// Build the token endpoint URL using Microsoft identity platform v2.0
	tokenURL := fmt.Sprintf("https://login.microsoftonline.com/%s/oauth2/v2.0/token", tenantID)

	// Configure the OAuth2 client credentials
	config := &clientcredentials.Config{
		ClientID:     clientID,
		ClientSecret: clientSecret,
		TokenURL:     tokenURL,
		Scopes:       []string{fmt.Sprintf("api://%s/.default", clientID)},
	}

	// Create an HTTP client that automatically handles token refresh
	httpClient := config.Client(ctx)
	httpClient.Timeout = DefaultTimeout

	return &Client{
		serverURL:  serverURL,
		httpClient: httpClient,
	}, nil
}

// doRequest performs an HTTP request and returns the response body.
func (c *Client) doRequest(ctx context.Context, method, path string, body io.Reader) ([]byte, error) {
	reqURL := fmt.Sprintf("%s%s", c.serverURL, path)

	req, err := http.NewRequestWithContext(ctx, method, reqURL, body)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("API request failed with status %d: %s", resp.StatusCode, string(respBody))
	}

	return respBody, nil
}

// Get performs a GET request.
func (c *Client) Get(ctx context.Context, path string) ([]byte, error) {
	return c.doRequest(ctx, http.MethodGet, path, nil)
}

// Post performs a POST request.
func (c *Client) Post(ctx context.Context, path string, body io.Reader) ([]byte, error) {
	return c.doRequest(ctx, http.MethodPost, path, body)
}

// Put performs a PUT request.
func (c *Client) Put(ctx context.Context, path string, body io.Reader) ([]byte, error) {
	return c.doRequest(ctx, http.MethodPut, path, body)
}

// Delete performs a DELETE request.
func (c *Client) Delete(ctx context.Context, path string) ([]byte, error) {
	return c.doRequest(ctx, http.MethodDelete, path, nil)
}

// WaitForJob polls a job until it completes or fails.
func (c *Client) WaitForJob(ctx context.Context, jobID string) (*Job, error) {
	path := fmt.Sprintf("/api/v1/jobs/%s", url.PathEscape(jobID))

	for attempt := 0; attempt < JobPollMaxAttempts; attempt++ {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(JobPollInterval):
		}

		respBody, err := c.Get(ctx, path)
		if err != nil {
			return nil, fmt.Errorf("failed to poll job status: %w", err)
		}

		var job Job
		if err := json.Unmarshal(respBody, &job); err != nil {
			return nil, fmt.Errorf("failed to parse job response: %w", err)
		}

		switch job.Status {
		case JobStatusCompleted:
			return &job, nil
		case JobStatusFailed:
			errMsg := "job failed"
			if job.Error != nil {
				errMsg = *job.Error
			}
			return &job, fmt.Errorf("job %s failed: %s", jobID, errMsg)
		case JobStatusPending, JobStatusRunning:
			// Continue polling
		default:
			return nil, fmt.Errorf("unknown job status: %s", job.Status)
		}
	}

	return nil, fmt.Errorf("job %s did not complete within the expected time", jobID)
}

// HealthCheck verifies the API server is reachable and healthy.
func (c *Client) HealthCheck(ctx context.Context) error {
	_, err := c.Get(ctx, "/healthz")
	return err
}

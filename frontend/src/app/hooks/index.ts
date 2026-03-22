/**
 * React Hooks for API calls
 */

import { useState, useEffect } from 'react';
import { workbenchApi, itemApi, analysisApi, outputApi } from '../lib/api';
import type {
  WorkbenchHomeData,
  TodosData,
  ItemTimelineData,
  Analysis,
  Output,
  OutputListItem,
} from '../types';

/**
 * Hook: 获取工作台首页数据
 */
export function useWorkbenchHome() {
  const [data, setData] = useState<WorkbenchHomeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        setError(null);
        const response = await workbenchApi.getHome();
        setData(response.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载数据失败');
        console.error('Failed to fetch workbench home:', err);
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  return { data, loading, error };
}

/**
 * Hook: 获取待办列表
 */
export function useWorkbenchTodos() {
  const [data, setData] = useState<TodosData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        setError(null);
        const response = await workbenchApi.getTodos();
        setData(response.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载待办失败');
        console.error('Failed to fetch todos:', err);
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  return { data, loading, error };
}

/**
 * Hook: 获取事项时间线
 */
export function useItemTimeline(itemId: number | null) {
  const [data, setData] = useState<ItemTimelineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!itemId) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await itemApi.getTimeline(itemId);
      setData(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载时间线失败');
      console.error('Failed to fetch item timeline:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [itemId]);

  return { data, loading, error, refetch: fetchData };
}

/**
 * Hook: 获取分析详情
 */
export function useAnalysis(analysisId: number | null) {
  const [data, setData] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!analysisId) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await analysisApi.getById(analysisId);
      setData(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载分析详情失败');
      console.error('Failed to fetch analysis:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [analysisId]);

  return { data, loading, error, refetch: fetchData };
}

/**
 * Hook: 获取事项的输出列表
 */
export function useOutputsByItem(itemId: number | null) {
  const [data, setData] = useState<OutputListItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!itemId) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await outputApi.getByItemId(itemId);
      setData(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载输出列表失败');
      console.error('Failed to fetch outputs:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [itemId]);

  return { data, loading, error, refetch: fetchData };
}

/**
 * Hook: 获取输出详情
 */
export function useOutput(outputId: number | null) {
  const [data, setData] = useState<Output | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!outputId) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await outputApi.getById(outputId);
      setData(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载输出详情失败');
      console.error('Failed to fetch output:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [outputId]);

  return { data, loading, error, refetch: fetchData };
}
